"""阶段 6 自测脚本（锁定 mock 模式，离线运行，不联网）。

运行方式:
    cd backend && .venv/bin/python tests/selftest_phase6.py

- 导入前强制 STOCK_DATA_MODE=mock + 临时数据目录（不污染真实 DB/缓存）
- 覆盖 implementation-plan.md 阶段 6 审核检查点:
    1 CRUD（增改删查、刷新保持） / 2 实时计算字段 / 3 VaR 合理性 /
    4 最大回撤 / 5 相关性矩阵 / 6 集中度 / 7 净值曲线 / 8 空状态
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="stockpanel_p6_")
os.environ["STOCK_DATA_MODE"] = "mock"
os.environ["STOCKPANEL_DATA_DIR"] = _TMP
os.environ["MYSQL_HOST"] = ""                  # 锁定 SQLite 回退，不受 backend/.env 影响

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from models.database import init_db

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def test_crud():
    print("\n[1] 持仓 CRUD + 实时计算")
    from api import portfolio as api

    async def flow():
        # 空列表
        empty = await api.list_holdings()
        # 添加两只（mock 数据真实存在）
        h1 = await api.add_holding(api.HoldingCreate(
            stock_code="600519", quantity=100, cost_price=1200.0,
            buy_date="2026-01-15"))
        h2 = await api.add_holding(api.HoldingCreate(
            stock_code="000001", quantity=1000, cost_price=10.0))
        listed = await api.list_holdings()
        # 修改
        upd = await api.update_holding(
            h1.id, api.HoldingUpdate(quantity=200, notes="加仓"))
        # 删除失败场景
        gone = await api.remove_holding(h2.id)
        return empty, h1, h2, listed, upd, gone

    empty, h1, h2, listed, upd, gone = asyncio.run(flow())
    check("初始为空", empty.summary.count == 0)
    check("名称自动填充", h1.stock_name == "贵州茅台", h1.stock_name)
    check("现价来自 mock", h1.latest_price is not None and h1.latest_price > 0,
          str(h1.latest_price))
    check("市值 = 现价×数量", h1.market_value == round(h1.latest_price * h1.quantity, 2))
    check("盈亏 = (现价-成本)×数量", h1.profit == round((h1.latest_price - 1200.0) * 100, 2))
    check("盈亏率", h1.profit_pct == round((h1.latest_price / 1200.0 - 1) * 100, 2))
    check("持有天数 ≥0", h1.hold_days is not None and h1.hold_days >= 0)
    check("列表 2 条", listed.summary.count == 2)
    check("汇总总成本", abs(listed.summary.total_cost - (120000.0 + 10000.0)) < 1e-6)
    check("汇总总市值", abs(listed.summary.total_market_value
                          - (h1.latest_price * 100 + h2.latest_price * 1000)) < 0.02)
    check("占比合计 ≈ 100%",
          abs(sum(h.weight for h in listed.holdings) - 100.0) < 0.01)
    check("修改数量生效", upd.quantity == 200 and upd.notes == "加仓")
    check("删除成功", gone["ok"] is True)
    listed2 = asyncio.run(api.list_holdings())
    check("删除后 1 条", listed2.summary.count == 1)
    check("data_meta 透传来源", listed2.data_meta.get("source") is not None
          or len(listed2.data_meta.get("warnings", [])) == 0)
    return listed2


def test_risk_flow(listed):
    print("\n[2] 风险评估全流程（mock 数据）")
    from api import portfolio as api

    risk = asyncio.run(api.portfolio_risk())
    check("完整指标结构", {"var", "max_drawdown", "volatility", "beta", "sharpe",
                            "concentration", "sector_exposure", "correlation",
                            "portfolio_curve", "risk_level"} <= set(risk.keys()))
    check("VaR 95% 在合理范围", risk["var"]["95"]["pct"] is not None
          and 0.5 < risk["var"]["95"]["pct"] < 15,
          str(risk["var"]["95"]))
    check("VaR 99% ≥ 95%", (risk["var"]["99"]["pct"] or 0) >= (risk["var"]["95"]["pct"] or 0))
    check("最大回撤有起止日期", risk["max_drawdown"]["start"] is not None
          and risk["max_drawdown"]["end"] is not None
          and risk["max_drawdown"]["max"] > 0)
    check("波动率年化合理", risk["volatility"]["portfolio"] is not None
          and 5 < risk["volatility"]["portfolio"] < 120,
          str(risk["volatility"]["portfolio"]))
    check("Beta 在 [-3, 3]", risk["beta"] is not None and -3 < risk["beta"] < 3,
          str(risk["beta"]))
    check("夏普在 [-5, 5]", risk["sharpe"] is not None and -5 < risk["sharpe"] < 5,
          str(risk["sharpe"]))
    check("HHI = 单一持仓 1.0", risk["concentration"]["hhi"] == 1.0
          and risk["concentration"]["level"] == "高集中")
    corr = asyncio.run(api.portfolio_correlation())
    check("单持仓矩阵对角线=1", corr["matrix"] and abs(corr["matrix"][0][0] - 1) < 1e-9)
    check("净值曲线 ≥60 点", len(risk["portfolio_curve"]["portfolio"]) >= 60)
    check("净值曲线含基准", len(risk["portfolio_curve"]["benchmark"]) >= 60)
    check("行业暴露 1 行业", risk["sector_exposure"]["count"] == 1)
    check("风险等级输出", risk["risk_level"] in ("高风险", "中风险", "低风险"))
    return risk


def test_empty_state():
    print("\n[3] 空状态与边界")
    from api import portfolio as api

    # 清空全部持仓 → 空状态
    listed = asyncio.run(api.list_holdings())
    async def clear():
        for h in listed.holdings:
            await api.remove_holding(h.id)
    asyncio.run(clear())
    empty = asyncio.run(api.list_holdings())
    check("清空后 count=0", empty.summary.count == 0)
    risk_empty = asyncio.run(api.portfolio_risk())
    check("无持仓 → 引导评估", risk_empty["incomplete"] is True
          and risk_empty["risk_level"] is None
          and "请先添加" in risk_empty["note"])
    corr_empty = asyncio.run(api.portfolio_correlation())
    check("无持仓相关性空矩阵", corr_empty["codes"] == [] and corr_empty["matrix"] == [])
    # mock 模式对未知代码会合成演示数据（阶段2 设计），
    # 代码有效性校验仅在真实模式下生效（上游无数据 → 400），此处验证不崩溃即可
    weird = asyncio.run(api.add_holding(api.HoldingCreate(
        stock_code="999999", quantity=1, cost_price=1.0)))
    check("未知代码 mock 合成不崩溃", weird.stock_name is not None)
    await_removed = asyncio.run(api.remove_holding(weird.id))
    check("清理成功", await_removed["ok"] is True)


def main() -> int:
    asyncio.run(init_db())
    listed = test_crud()
    test_risk_flow(listed)
    test_empty_state()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败  (临时数据目录: {_TMP})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
