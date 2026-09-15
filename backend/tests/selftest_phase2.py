"""阶段2 自测脚本（阶段3 修订：显式锁定 mock 模式，离线运行，不联网）。

运行方式:
    cd backend && .venv/bin/python tests/selftest_phase2.py

- 强制 STOCK_DATA_MODE=mock（阶段3 起 DataFetcher 默认读取 .env，
  本脚本在导入前覆盖环境变量，保证契约自测不触网）
- 缓存路径: <CACHE_DIR>/<provider>/<subdir>/（阶段3 v2 结构）

覆盖 implementation-plan.md 阶段2 审核检查点:
    1 桩数据完整性 / 2 缓存写入 / 3 缓存读取 / 4 缓存过期 / 6 API 契约字段
（检查点 5 搜索功能在浏览器中人工验证）
"""
from __future__ import annotations

import os

os.environ["STOCK_DATA_MODE"] = "mock"  # 锁定 mock，导入前设置

import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from services.cache import clear_cache, get_cache_stats
from services.data_fetcher import DataFetcher

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def main() -> int:
    settings.ensure_dirs()
    f = DataFetcher()
    clear_cache()

    print("\n[1] 桩数据完整性")
    stock_list = f.get_stock_list()
    check("get_stock_list ≥20 只真实A股", len(stock_list) >= 20, f"got {len(stock_list)}")
    check("stock_list 列: code/name/industry/market",
          list(stock_list.columns) == ["code", "name", "industry", "market"])
    check("贵州茅台在列表中", (stock_list["name"] == "贵州茅台").any())

    kline = f.get_kline("600519")
    check("get_kline 250 条", len(kline) == 250, f"got {len(kline)}")
    check("kline 列契约",
          list(kline.columns) == ["date", "open", "close", "high", "low", "volume",
                                  "amount", "amplitude", "pct_change", "change", "turnover"])
    check("kline 价格合理 (low<=open/close<=high)",
          bool(((kline["low"] <= kline[["open", "close"]].min(axis=1)) &
                (kline["high"] >= kline[["open", "close"]].max(axis=1))).all()))
    check("kline 周K可生成", len(f.get_kline("600519", period="weekly")) in range(48, 60))
    check("kline 月K可生成", len(f.get_kline("600519", period="monthly")) in range(9, 14))
    check("kline 日期过滤生效",
          bool((f.get_kline("600519", start_date="2026-06-01")["date"] >= "2026-06-01").all()))

    info = f.get_stock_info("600519")
    required_info = {"name", "industry", "market_cap", "pe", "pb", "total_shares", "float_shares"}
    check("get_stock_info 关键字段", required_info <= set(info.keys()), str(info.keys()))
    check("info.latest_price 与 kline 终点一致",
          abs(info["latest_price"] - float(kline.iloc[-1]["close"])) < 1e-6)

    fin = f.get_financial_indicator("600519")
    check("get_financial_indicator 8 期", len(fin) == 8, f"got {len(fin)}")
    check("fin 列契约",
          list(fin.columns) == ["date", "ann_date", "roe", "roa", "gross_margin",
                                "net_margin", "revenue_growth", "profit_growth",
                                "debt_ratio", "eps", "bps", "current_ratio"])

    flow = f.get_fund_flow("600519")
    check("get_fund_flow 30 天", len(flow) == 30, f"got {len(flow)}")
    check("fund_flow 列契约",
          list(flow.columns) == ["date", "main_net_inflow", "main_net_inflow_pct",
                                 "super_large_net", "large_net", "medium_net", "small_net"])
    main_part = (flow["super_large_net"] + flow["large_net"] - flow["main_net_inflow"]).abs()
    rest_part = (flow["medium_net"] + flow["small_net"] + flow["main_net_inflow"]).abs()
    check("fund_flow 超大单+大单≈主力", bool((main_part < 0.03).all()))
    check("fund_flow 中单+小单≈-主力", bool((rest_part < 0.03).all()))

    news = f.get_stock_news("600519")
    check("get_stock_news 10 条", len(news) == 10, f"got {len(news)}")
    check("news 列: title/content/pub_time/source",
          list(news.columns) == ["title", "content", "pub_time", "source"])

    idx = f.get_index_data("000001")
    check("get_index_data 列契约",
          list(idx.columns) == ["date", "open", "close", "high", "low", "volume", "amount"])
    check("上证指数点位合理", 2000 < idx.iloc[-1]["close"] < 8000)

    boards = f.get_industry_board_list()
    check("get_industry_board_list 列契约",
          list(boards.columns) == ["name", "code", "pct_change", "turnover",
                                   "leading_stock", "leading_pct"])
    check("板块 ≥10 个", len(boards) >= 10, f"got {len(boards)}")

    bh = f.get_industry_board_hist("白酒")
    check("get_industry_board_hist 列契约",
          list(bh.columns) == ["date", "open", "close", "high", "low", "volume",
                               "amount"])

    mflow = f.get_market_fund_flow()
    check("get_market_fund_flow 30 天", len(mflow) == 30, f"got {len(mflow)}")

    val = f.get_stock_valuation("600519")
    check("get_stock_valuation 键",
          {"pe_ttm", "pe_static", "pb", "ps", "pcf", "dividend_yield", "market_cap"}
          <= set(val.keys()))

    check("get_profit_sheet 列契约",
          list(f.get_profit_sheet("600519").columns) ==
          ["REPORT_DATE", "ANN_DATE", "F_ANN_DATE", "OPERATE_INCOME",
           "TOTAL_REVENUE", "OPERATE_COST", "OPERATE_PROFIT", "TOTAL_PROFIT",
           "INCOME_TAX", "NETPROFIT", "PARENT_NETPROFIT"])
    check("get_balance_sheet 列契约",
          list(f.get_balance_sheet("600519").columns) ==
          ["REPORT_DATE", "ANN_DATE", "F_ANN_DATE", "TOTAL_ASSETS",
           "TOTAL_LIABILITIES", "TOTAL_EQUITY", "MONETARYFUNDS", "ACCOUNTS_RECE",
           "INVENTORY", "CURRENT_ASSETS"])
    check("get_cashflow_sheet 列契约",
          list(f.get_cashflow_sheet("600519").columns) ==
          ["REPORT_DATE", "ANN_DATE", "F_ANN_DATE", "NETCASH_OPERATE",
           "NETCASH_INVEST", "NETCASH_FINANCE", "CCE_ADD"])
    check("get_holder_info 10 大股东", len(f.get_holder_info("600519")) == 10)
    check("get_dividend_history 结构",
          list(f.get_dividend_history("600519").columns) ==
          ["report_date", "dividend", "stock_bonus", "stock_transfer", "ex_date",
           "ann_date"])

    pe_pb = f.get_industry_pe_pb("白酒")
    check("get_industry_pe_pb 键契约",
          {"pe_median", "pb_median", "pe_mean", "pb_mean", "stock_count"}
          <= set(pe_pb.keys()))

    print("\n[2] 缓存写入")
    stats = get_cache_stats()
    check("调用后生成缓存文件", stats["file_count"] > 0,
          f"cache_dir={stats['cache_dir']}, count={stats['file_count']}")
    provider_dir = settings.CACHE_DIR / "mock"
    kline_cache = provider_dir / "kline"
    check("kline 子目录有文件", any(kline_cache.glob("*.json")))
    check("stock_list 固定文件存在", (provider_dir / "stock_list.json").is_file())
    check("info 子目录有文件", any((provider_dir / "info").glob("*.json")))
    check("financial 子目录有文件", any((provider_dir / "financial").glob("*.json")))
    # 精确锁定 get_kline("600519") 日K对应的缓存文件（250 条记录的那个）
    daily_closes = [round(float(x), 2) for x in kline["close"]]
    kline_files = list(kline_cache.glob("*.json"))
    def _closes_match(path: Path) -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("records") or []
            return ([round(float(r["close"]), 2) for r in records if "close" in r]
                    == daily_closes)
        except (OSError, ValueError, TypeError, KeyError):
            return False

    sample = next((p for p in kline_files if _closes_match(p)), None)
    check("锁定日K缓存文件", sample is not None)
    assert sample is not None
    payload = json.loads(sample.read_text(encoding="utf-8"))
    check("缓存文件含 _cached_at", "_cached_at" in payload)

    print("\n[3] 缓存读取（二次调用不重新生成）")
    mtime_before = sample.stat().st_mtime_ns
    time.sleep(0.05)
    f.get_kline("600519")  # 第二次调用应直接读缓存
    check("二次调用未重写缓存文件", sample.stat().st_mtime_ns == mtime_before)

    print("\n[4] 缓存过期（改 _cached_at 后重新生成）")
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["_cached_at"] = time.time() - settings.CACHE_TTL_KLINE * 2
    sample.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    stale_cached_at = payload["_cached_at"]
    f.get_kline("600519")
    payload2 = json.loads(sample.read_text(encoding="utf-8"))
    check("过期后重新生成并刷新 _cached_at", payload2["_cached_at"] > stale_cached_at)
    check("重新生成后数据确定性一致（同种子）",
          [r["close"] for r in payload2["records"]] ==
          [r["close"] for r in payload["records"]])

    print("\n[5] 新闻不缓存")
    news_files_before = get_cache_stats()["file_count"]
    f.get_stock_news("600519")
    f.get_stock_news("600519")
    check("两次调用新闻未产生缓存文件", get_cache_stats()["file_count"] == news_files_before)

    print("\n[6] 搜索匹配逻辑（api.stock.search_stocks）")
    from api.stock import _search_impl

    by_name = [s.code for s in _search_impl(q="贵州")[0]]
    check("名称包含'贵州'命中茅台", "600519" in by_name, str(by_name))
    by_code = [s.code for s in _search_impl(q="600")[0]]
    check("代码前缀'600'命中多只", len(by_code) >= 5, str(by_code))
    check("搜索结果 ≤20", len(_search_impl(q="6")[0]) <= 20)
    check("无匹配返回空", _search_impl(q="不存在的股票xyz")[0] == [])

    print("\n[7] 清空缓存")
    removed = clear_cache()
    check("clear_cache 删除文件数>0", removed > 0, f"removed={removed}")
    check("清空后 file_count=0", get_cache_stats()["file_count"] == 0)

    print(f"\n结果: {PASS} 通过, {FAIL} 失败  (缓存目录: {settings.CACHE_DIR})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
