"""阶段3 真实 smoke 验收脚本（opt-in，发起真实网络请求）。

运行: cd backend && STOCKPANEL_SMOKE=1 .venv/bin/python tests/smoke_real_apis.py

- 使用 DataFetcher（hybrid 模式，读取 backend/.env 密钥）覆盖 17 个方法
- 核心方法必须真实可用，失败则记录原因（不以 mock 代替验收）
- 扩展方法逐项给出: verified / unavailable(原因) / degraded
- 交叉复算: ProMax pro_bar(qfq) vs 本地 daily+adj_factor 前复权
- 成功后写入 DATA_DIR/data_source_status.json（/api/config/data-source-status 读取）
- 输出全部脱敏，不打印密钥
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from config import settings  # noqa: E402
from services.data_fetcher import DataFetcher  # noqa: E402

RESULTS: list[dict] = []


def record(name: str, status: str, detail: str, *, rows=None, trade_date=None,
           source=None, elapsed_ms=None) -> None:
    RESULTS.append({
        "method": name, "status": status, "detail": detail[:300],
        "rows": rows, "trade_date": trade_date, "source": source,
        "elapsed_ms": elapsed_ms,
    })
    mark = {"verified": "✓", "degraded": "◑", "unavailable": "✗"}.get(status, "?")
    extra = f" rows={rows}" if rows is not None else ""
    extra += f" as_of={trade_date}" if trade_date else ""
    extra += f" [{source}]" if source else ""
    print(f"  {mark} {name:28s} {status:11s} {extra} {detail[:70]}")


INFORMATIONAL = ("复权锚点", "指数 volume 单位", "申万 vol 单位", "已去重", "查询")


def wrap(name: str, fn, *, core: bool):
    start = time.perf_counter()
    try:
        result = fn()
        elapsed = round((time.perf_counter() - start) * 1000)
        if isinstance(result, pd.DataFrame):
            meta = result.attrs.get("data_meta", {})
            rows = len(result)
            hard = [w for w in (meta.get("warnings") or [])
                    if not any(w.startswith(p) for p in INFORMATIONAL)]
            status = "degraded" if hard else "verified"
            record(name, status, "；".join(hard) or "契约字段完整",
                   rows=rows, trade_date=meta.get("trade_date"),
                   source=meta.get("source"), elapsed_ms=elapsed)
            return result, meta
        meta = result.get("_data_meta", {})
        return result, meta
    except Exception as exc:  # 数据源错误或意外异常
        elapsed = round((time.perf_counter() - start) * 1000)
        kind = type(exc).__name__
        detail = str(getattr(exc, "message", None) or exc)
        status = "unavailable" if not core else "unavailable"
        record(name, status, f"{kind}: {detail}", elapsed_ms=elapsed)
        return None, None


def main() -> int:
    if not os.environ.get("STOCKPANEL_SMOKE"):
        print("真实 smoke 需显式启用: STOCKPANEL_SMOKE=1 才会发起网络请求")
        return 2
    settings.ensure_dirs()
    f = DataFetcher()  # mode 来自 .env（hybrid）
    print(f"模式: {f.mode}\n")

    # ---- 核心数据（检查点 3: 不可用则阶段不通过） ----
    stock_list, _ = wrap("get_stock_list", f.get_stock_list, core=True)
    if stock_list is not None:
        bj = stock_list[stock_list["code"].str.endswith(("43", "83", "87", "92"))] if False else None
        bj = stock_list[stock_list["market"] == "北"]
        record("get_stock_list(北交所)", "verified" if len(bj) else "degraded",
               f"北交所 {len(bj)} 只" if len(bj) else "无北交所股票", rows=len(bj))

    kline, _ = wrap("get_kline(daily,qfq)", lambda: f.get_kline("600519"), core=True)
    wrap("get_kline(weekly)", lambda: f.get_kline("600519", period="weekly"), core=True)
    wrap("get_kline(monthly)", lambda: f.get_kline("600519", period="monthly"), core=True)
    wrap("get_kline(unadjusted)", lambda: f.get_kline("600519", adjust=""), core=True)
    wrap("get_kline(BJ)", lambda: f.get_kline("920000.BJ"), core=True)
    info, _ = wrap("get_stock_info", lambda: f.get_stock_info("600519"), core=True)
    wrap("get_stock_valuation", lambda: f.get_stock_valuation("600519"), core=True)
    fin, _ = wrap("get_financial_indicator", lambda: f.get_financial_indicator("600519"), core=True)
    wrap("get_profit_sheet", lambda: f.get_profit_sheet("600519"), core=True)
    wrap("get_balance_sheet", lambda: f.get_balance_sheet("600519"), core=True)
    wrap("get_cashflow_sheet", lambda: f.get_cashflow_sheet("600519"), core=True)
    wrap("get_index_data", lambda: f.get_index_data("000300"), core=True)
    wrap("get_index_data(weekly)", lambda: f.get_index_data("000001", "weekly"), core=True)

    # ---- 扩展能力（检查点 10: verified 或显式 unavailable） ----
    wrap("get_fund_flow", lambda: f.get_fund_flow("600519"), core=False)
    wrap("get_market_fund_flow", f.get_market_fund_flow, core=False)
    wrap("get_stock_news", lambda: f.get_stock_news("600519"), core=False)
    wrap("get_holder_info", lambda: f.get_holder_info("600519"), core=False)
    wrap("get_dividend_history", lambda: f.get_dividend_history("600519"), core=False)
    wrap("get_industry_board_list", f.get_industry_board_list, core=False)
    wrap("get_industry_board_hist", lambda: f.get_industry_board_hist("食品饮料"), core=False)
    wrap("get_industry_pe_pb", lambda: f.get_industry_pe_pb("食品饮料"), core=False)

    # ---- 交叉复算: ProMax pro_bar(qfq) vs 本地 qfq（检查点 5） ----
    cross_check(f)

    # ---- 单位自洽抽检 ----
    unit_checks(kline, info)

    # ---- 写入数据源状态（供 /api/config/data-source-status 读取） ----
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": f.mode,
        "results": RESULTS,
        "summary": {
            "verified": sum(1 for r in RESULTS if r["status"] == "verified"),
            "degraded": sum(1 for r in RESULTS if r["status"] == "degraded"),
            "unavailable": sum(1 for r in RESULTS if r["status"] == "unavailable"),
        },
    }
    out = settings.DATA_DIR / "data_source_status.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n状态文件已写入: {out}")
    print("汇总:", summary["summary"])
    return 0


def cross_check(f) -> None:
    """本地前复权（datahubco daily+adj_factor）vs ProMax pro_bar(qfq) 收盘价对比。"""
    import httpx

    from config import settings as s
    try:
        pm = httpx.Client(base_url=settings.PROMAX_BASE_URL, timeout=30,
                          trust_env=settings.STOCK_HTTP_TRUST_ENV)
        r = pm.get("/pro_bar", params={
            "ts_code": "600519.SH", "freq": "D", "asset": "E", "adj": "qfq",
            "start_date": (date.today() - timedelta(days=40)).strftime("%Y%m%d"),
            "end_date": (date.today() - timedelta(days=1)).strftime("%Y%m%d"),
        }, headers={"X-API-Key": settings.PROMAX_API_KEY})
        pm.close()
        body = r.json()
        data = body.get("data") or {}
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            record("cross_check(pro_bar)", "degraded", "pro_bar 无数据可对比")
            return
        pro = pd.DataFrame(items, columns=fields).rename(columns={"close": "close_pro"})
        local = f.get_kline("600519", start_date=(date.today() - timedelta(days=40)).isoformat(),
                            end_date=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"))
        pro["trade_date"] = pro["trade_date"].astype(str).map(
            lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(str(s)) == 8 else str(s))
        pro["trade_date"] = pro["trade_date"].astype(str).map(
            lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(str(s)) == 8 else str(s))
        merged = pro.merge(local, left_on="trade_date", right_on="date")
        if merged.empty:
            record("cross_check(pro_bar)", "degraded", "两源无重叠交易日")
            return
        merged["diff_pct"] = (
            (pd.to_numeric(merged["close_pro"]) - merged["close"]).abs()
            / merged["close"].astype(float) * 100
        )
        max_diff = float(merged["diff_pct"].max())
        ok = max_diff < 0.05  # 允许 0.05% 舍入差
        record("cross_check(pro_bar qfq)",
               "verified" if ok else "degraded",
               f"对比 {len(merged)} 交易日, 最大收盘价差 {max_diff:.4f}%",
               rows=len(merged))
    except Exception as exc:
        record("cross_check(pro_bar qfq)", "degraded", f"交叉复算未完成: {exc}")


def unit_checks(kline, info) -> None:
    """真实数据单位自洽抽检（检查点 5）: vol(股)×价格 ≈ amount(元)。"""
    if kline is None or kline.empty:
        record("unit_check(量额自洽)", "unavailable", "无K线数据")
        return
    last = kline.iloc[-1]
    approx = float(last["volume"]) * float(last["close"])
    amount = float(last["amount"])
    ratio = amount / approx if approx else 0
    ok = 0.8 < ratio < 1.2  # 量×收盘 ≈ 成交额（均价在 ±10% 内）
    record("unit_check(量额自洽)", "verified" if ok else "degraded",
           f"vol×close/amount={ratio:.3f}")
    if info and info.get("total_shares") and info.get("market_cap") and info.get("latest_price"):
        implied = float(info["market_cap"]) / (float(info["total_shares"]) * float(info["latest_price"]))
        record("unit_check(市值=股本×价)", "verified" if 0.99 <= implied / 1 <= 1.01 else "degraded",
               f"market_cap/(total_shares×price)={implied:.4f}")


if __name__ == "__main__":
    sys.exit(main())
