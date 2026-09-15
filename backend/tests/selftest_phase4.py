"""阶段 4 自测脚本（锁定 mock 模式，离线运行，不联网）。

运行方式:
    cd backend && .venv/bin/python tests/selftest_phase4.py

- 导入前强制 STOCK_DATA_MODE=mock + 临时数据目录（不污染真实 DB/缓存）
- 覆盖 implementation-plan.md 阶段 4 审核检查点:
    3 技术评分方向 / 4 基本面评分 / 5 评级映射 / 6 报告完整性 / 8 降级逻辑
  （检查点 1/2 指标与信号计算由 test_technical_engine.py 覆盖；
    检查点 7 SSE 由 /report 端点 + 事件序列断言覆盖）
"""
from __future__ import annotations

import os

import tempfile

_TMP = tempfile.mkdtemp(prefix="stockpanel_p4_")
os.environ["STOCK_DATA_MODE"] = "mock"          # 锁定 mock，导入前设置
os.environ["STOCKPANEL_DATA_DIR"] = _TMP        # 隔离 DB 与缓存

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

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


def test_technical_on_mock():
    print("\n[1] TechnicalEngine on mock K线")
    from services.data_fetcher import get_data_fetcher
    from services.technical import TechnicalEngine
    f = get_data_fetcher()
    kline = f.get_kline("600519", adjust="qfq")   # 默认 420 自然日 ≈285 交易日
    check("mock K线 ≥250 行(MA250 需求)", len(kline) >= 250, str(len(kline)))
    e = TechnicalEngine()
    result = e.get_technical_score(kline)
    check("产出评分", result["score"] is not None and result["rating"] is not None,
          str(result))
    check("分数在 ±100", -100 <= result["score"] <= 100, str(result["score"]))
    for comp in ("trend", "oscillator", "channel", "volume"):
        c = result["components"][comp]
        check(f"{comp} 子分 ±100", -100 <= c["score"] <= 100, str(c["score"]))
        check(f"{comp} 有信号明细", isinstance(c["signals"], list))
    check("信号非空", len(result["signals"]) > 0)
    series = e.indicator_series(kline)
    check("画图序列含 ma/macd/kdj/boll/volume",
          set(series.keys()) >= {"dates", "ma", "macd", "kdj", "boll", "volume"})
    check("ma 序列长度=K线行数", len(series["ma"]["ma_5"]) == len(kline))


def test_fundamental_on_mock():
    print("\n[2] FundamentalEngine on mock 数据")
    from services.data_fetcher import get_data_fetcher
    from services.fundamental import FundamentalEngine
    f = get_data_fetcher()
    ts = "600519.SH"
    info = f.get_stock_info(ts)
    valuation = f.get_stock_valuation(ts)
    ind_pepb = f.get_industry_pe_pb("白酒")
    fin = {
        "fina_indicator": f.get_financial_indicator(ts),
        "income": f.get_profit_sheet(ts),
        "balance": f.get_balance_sheet(ts),
        "cashflow": f.get_cashflow_sheet(ts),
        "industry_pe_pb": ind_pepb,
    }
    e = FundamentalEngine()
    merged = {**info, **{k: v for k, v in valuation.items() if k != "_data_meta"}}
    result = e.get_fundamental_score(merged, fin)
    check("产出评分", result["score"] is not None, str(result["score"]))
    check("三维子分存在", all(
        result[d]["score"] is not None for d in ("valuation", "growth", "health")))
    check("分数在 ±100", -100 <= result["score"] <= 100, str(result["score"]))
    check("财务数据齐备", result["incomplete"] is False)
    check("估值含行业对比", result["valuation"]["items"][0].get("industry_median") is not None
          or "warning" in ind_pepb)


def test_report_builder_flow():
    print("\n[3] ReportBuilder 全流程（SSE 事件序列 + 报告完整性）")
    from services.report_builder import ReportBuilder
    builder = ReportBuilder()
    stages, report = [], None
    for ev in builder.build_report("600519"):
        if ev.get("stage") == "report":
            report = ev["report"]
        else:
            stages.append(ev["stage"])
    # 阶段 8 起 ai_analysis 可能产出多条进度事件（情绪→综合点评），按首次出现顺序断言
    check("进度阶段完整",
          list(dict.fromkeys(stages)) == ["fetching_data", "technical_analysis",
                                          "fundamental_analysis", "ai_analysis",
                                          "building_report"], str(stages))
    check("report 终事件", report is not None)
    required = {"stock_info", "rating", "technical", "fundamental", "fund_flow",
                "news_sentiment", "ai_report", "kline_data", "indicator_data",
                "data_meta", "generated_at"}
    check("design 6.2 全字段", required <= set(report.keys()),
          str(required - set(report.keys())))
    check("data_meta 透传(来源+as_of)",
          report["data_meta"].get("source") is not None
          and report["data_meta"].get("as_of") is not None,
          str(report["data_meta"]))
    check("K线 ≥250 行(MA250 需求)", len(report["kline_data"]) >= 250)
    check("综合评级（50/50 回退）",
          report["rating"]["score"] is not None
          and report["rating"]["weights"] == {"technical": 0.5, "fundamental": 0.5,
                                              "sentiment": None},
          str(report["rating"]))
    check("AI 降级标注", report["news_sentiment"].get("note") is not None
          and report["ai_report"] is None)
    check("免责声明", "不构成投资建议" in report.get("disclaimer", ""))
    # 检查 kline_data 数值均为有限值或 None（无 NaN 泄漏）
    bad = [r for r in report["kline_data"][:20]
           for v in r.values() if v is not None and isinstance(v, float)
           and v != v]
    check("无 NaN 泄漏到 JSON", not bad, str(bad[:2]))
    return report


def test_report_history(report: dict):
    print("\n[4] report_history 写入与查询")
    from models.database import init_db, get_session_factory, ReportHistory
    from sqlalchemy import select
    asyncio.run(init_db())

    async def flow():
        from api.stock import _save_report_history
        await _save_report_history(report)
        async with get_session_factory()() as session:
            rows = (await session.execute(
                select(ReportHistory).order_by(ReportHistory.id.desc())
                .limit(5))).scalars().all()
            return rows

    rows = asyncio.run(flow())
    check("写入 1 条", len(rows) >= 1, str(len(rows)))
    top = rows[0]
    info = report["stock_info"]
    check("code/name 正确", top.stock_code == info["code"]
          and top.stock_name == info["name"], f"{top.stock_code} {top.stock_name}")
    check("score 与报告一致",
          abs(top.score - float(report["rating"]["score"])) < 1e-6,
          f"{top.score} vs {report['rating']['score']}")


def test_api_routes():
    print("\n[5] API 路由直调（mock 模式）")
    import api.stock as api
    t = api.get_technical("600519", days=250)
    check("/technical 产出评分", t["score"] is not None and t["rating"] is not None)
    check("/technical 含画图序列", "indicator_series" in t)
    fd = api.get_fundamental("600519")
    check("/fundamental 产出评分", fd["score"] is not None)
    check("/fundamental 三维齐全",
          {"valuation", "growth", "health"} <= set(fd.keys()))
    hist = asyncio.run(api.stock_report_history("600519"))
    check("/report/history 返回记录", len(hist["items"]) >= 1, str(hist))


def main() -> int:
    report = None
    test_technical_on_mock()
    test_fundamental_on_mock()
    report = test_report_builder_flow()
    if report and report["rating"].get("score") is not None:
        test_report_history(report)
    test_api_routes()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败  (临时数据目录: {_TMP})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
