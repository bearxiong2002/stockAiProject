"""阶段 6.2 RiskEngine 离线正确性测试（已知数据验证，不联网）。

run: .venv/bin/python tests/test_risk_engine.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

from services.risk import RiskEngine

PASS = FAIL = 0


def check(name: str, cond, detail="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


class FakeFetcher:
    """可编程行情源: kline 映射 code → close 序列；指数另走 get_index_data。"""

    def __init__(self, closes: dict[str, list[float]]):
        self._closes = closes

    def get_index_data(self, index_code="000300", period="daily"):
        key = f"idx:{index_code}"
        closes = self._closes.get(key)
        if closes is None:
            raise KeyError(index_code)
        n = len(closes)
        return pd.DataFrame({
            "date": [f"d{i:04d}" for i in range(n)], "open": closes,
            "close": closes, "high": closes, "low": closes,
            "volume": [1e8] * n, "amount": [1e10] * n,
        })

    def get_kline(self, code, days=250, adjust="qfq"):
        closes = self._closes.get(str(code).split(".")[0], self._closes.get(str(code)))
        if closes is None:
            raise KeyError(code)
        n = len(closes)
        return pd.DataFrame({
            "date": [f"d{i:04d}" for i in range(n)],
            "open": closes, "close": closes, "high": closes, "low": closes,
            "volume": 1e6, "amount": 1e9, "amplitude": 2.0,
            "pct_change": pd.Series(closes).pct_change().fillna(0) * 100,
            "change": pd.Series(closes).diff().fillna(0), "turnover": 1.0,
        })


E = RiskEngine(FakeFetcher({}))


def test_var():
    print("\n[VaR 历史模拟]")
    rng = np.random.default_rng(11)
    r = rng.normal(0, 0.01, 1000)
    res = E.calc_var(r, 0.95, total_value=1_000_000)
    # 正态分布 95% 单日 VaR ≈ 1.645σ ≈ 1.645%
    check("95% VaR ≈ 1.65σ", abs(res["pct"] - 1.645) < 0.25, str(res))
    check("VaR 金额 = pct×市值", abs(res["amount"] - res["pct"] / 100 * 1_000_000) < 0.01)
    res99 = E.calc_var(r, 0.99)
    check("99% VaR > 95% VaR", res99["pct"] > res["pct"], f"{res99['pct']} vs {res['pct']}")
    check("样本不足 → None + 说明", E.calc_var(r[:10], 0.95)["pct"] is None)


def test_drawdown():
    print("\n[最大回撤]")
    # 峰值 1.2 @d1，谷值 0.8 @d3；余段恢复以构成完整回撤-修复形态
    nav = pd.Series([1.0, 1.2, 1.0, 0.8, 1.1, 1.3, 1.2, 1.15, 1.2, 1.25, 1.2, 1.28],
                    index=[f"d{i}" for i in range(12)])
    dd = E.calc_max_drawdown(nav)
    check("最大回撤 = (1-0.8/1.2) ≈ 33.3%",
          abs(dd["max"] - (1 - 0.8 / 1.2) * 100) < 0.05, str(dd))
    check("起点 = 峰值日", dd["start"] == "d1", str(dd))
    check("终点 = 谷值日", dd["end"] == "d3", str(dd))
    # 末值 1.28 低于历史峰值 1.3（d5）→ 当前回撤 1.54%
    check("当前回撤 = 1 - 1.28/1.3", abs(dd["current"] - (1 - 1.28 / 1.3) * 100) < 0.05, str(dd))
    check("样本不足 → None", E.calc_max_drawdown(nav.iloc[:5])["max"] is None)


def test_vol_beta_sharpe():
    print("\n[波动率 / Beta / 夏普]")
    rng = np.random.default_rng(3)
    idx = rng.normal(0, 0.01, 400)
    port = 1.5 * idx + rng.normal(0, 0.002, 400)
    check("波动率 σ×√250", abs(E.calc_volatility(port) - np.std(port, ddof=1) * math.sqrt(250) * 100) < 0.01)
    beta = E.calc_beta(port, idx)
    check("Beta ≈ 1.5（构造斜率）", abs(beta - 1.5) < 0.25, str(beta))
    ann_ret = np.mean(port) * 250
    vol = np.std(port, ddof=1) * math.sqrt(250)
    want = (ann_ret - 0.02) / vol
    check("夏普公式", abs(E.calc_sharpe(port) - want) < 1e-4, f"{E.calc_sharpe(port)} vs {want}")


def test_concentration_sector():
    print("\n[集中度 / 行业暴露]")
    holdings = [
        {"stock_code": "A", "quantity": 100, "latest_price": 10.0, "industry": "白酒"},
        {"stock_code": "B", "quantity": 100, "latest_price": 10.0, "industry": "白酒"},
        {"stock_code": "C", "quantity": 200, "latest_price": 10.0, "industry": "银行"},
        {"stock_code": "D", "quantity": 600, "latest_price": 10.0, "industry": "银行"},
    ]
    # 市值 1000/1000/2000/6000 → 权重 0.1/0.1/0.2/0.6
    conc = E.calc_concentration(holdings)
    check("HHI = 0.01+0.01+0.04+0.36 = 0.42", abs(conc["hhi"] - 0.42) < 1e-9, str(conc))
    check("前三大占比 = 90%", abs(conc["top3_pct"] - 90.0) < 1e-9)
    check("HHI>0.25 → 高集中", conc["level"] == "高集中")
    sector = E.calc_sector_exposure(holdings)
    top = sector["sectors"][0]
    check("行业占比排序（银行 80%）", top["industry"] == "银行"
          and abs(top["weight_pct"] - 80.0) < 1e-9, str(sector))
    check("单一行业 >40% 警告", any("银行" in w for w in sector["warnings"]), str(sector["warnings"]))
    check("行业数 = 2", sector["count"] == 2)
    # 分散样本
    five = [{"stock_code": chr(65 + i), "quantity": 1, "latest_price": 1.0, "industry": f"i{i}"}
            for i in range(6)]
    conc2 = E.calc_concentration(five)
    check("等权 6 只 HHI≈0.167 → 中等", abs(conc2["hhi"] - 1 / 6) < 1e-4
          and conc2["level"] == "中等", str(conc2))


def test_correlation_curve():
    print("\n[相关性矩阵 / 净值曲线]")
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.01, 300)
    a = 1 * base + rng.normal(0, 0.005, 300)   # 与 base 高相关
    b = 1 * base + rng.normal(0, 0.005, 300)
    c = rng.normal(0, 0.02, 300)               # 独立
    df = pd.DataFrame({"600519.SH": a, "000001.SZ": b, "300750.SZ": c})
    corr = E.calc_correlation_matrix(df)
    check("对角线 = 1", all(abs(corr["matrix"][i][i] - 1) < 1e-9 for i in range(3)))
    check("矩阵值域 [-1,1]", all(-1 <= v <= 1 for row in corr["matrix"] for v in row))
    check("高相关对检出（a,b > 0.7）", any(set(hp["pair"]) == {"600519.SH", "000001.SZ"}
                                         and hp["corr"] > 0.7 for hp in corr["high_pairs"]),
          str(corr["high_pairs"]))
    check("独立对不在高相关列表", not any(set(hp["pair"]) == {"600519.SH", "300750.SZ"}
                                            for hp in corr["high_pairs"]))

    # 净值曲线: A 权重 1.0（单持仓）→ 组合净值 = (1+ret_a).cumprod
    holdings = [{"stock_code": "600519.SH", "quantity": 100, "latest_price": 10.0,
                 "industry": "白酒"}]
    single = pd.DataFrame({"600519.SH": a})
    curve = E.calc_portfolio_curve(holdings, single)
    nav = (1 + pd.Series(a)).cumprod()
    check("单持仓净值 = 累积收益", abs(curve["portfolio"][-1] - nav.iloc[-1]) < 1e-3,
          f"{curve['portfolio'][-1]} vs {nav.iloc[-1]}")
    check("起点含首日收益", abs(curve["portfolio"][0] - (1 + a[0])) < 1e-4)


def test_full_assessment():
    print("\n[get_risk_assessment 汇总 + 空状态]")
    fetcher = FakeFetcher({
        "600519": list(np.linspace(1200, 1300, 260) * (1 + 0.01 * np.sin(np.arange(260)))),
        "000001": list(np.linspace(9, 11, 260) * (1 + 0.01 * np.sin(np.arange(260) + 1))),
        "idx:000300": list(np.linspace(3800, 4000, 260) * (1 + 0.008 * np.sin(np.arange(260)))),
    })
    engine = RiskEngine(fetcher)
    holdings = [
        {"stock_code": "600519", "quantity": 100, "latest_price": 1300.0,
         "industry": "白酒"},
        {"stock_code": "000001", "quantity": 1000, "latest_price": 11.0,
         "industry": "银行"},
    ]
    res = engine.get_risk_assessment(holdings)
    check("产出全部指标", {"var", "max_drawdown", "volatility", "beta", "sharpe",
                              "concentration", "sector_exposure", "correlation",
                              "portfolio_curve", "risk_level"} <= set(res.keys()))
    check("净值曲线含基准", len(res["portfolio_curve"]["benchmark"]) > 0)
    check("风险等级有效", res["risk_level"] in ("高风险", "中风险", "低风险"), res["risk_level"])
    check("无持仓 → incomplete", engine.get_risk_assessment([])["incomplete"] is True)
    short = FakeFetcher({"600519": [10] * 40, "000001": [5] * 40})
    res_short = RiskEngine(short).get_risk_assessment(
        [{"stock_code": "600519", "quantity": 1, "latest_price": 10.0},
         {"stock_code": "000001", "quantity": 1, "latest_price": 5.0}])
    check("样本不足 → incomplete", res_short["incomplete"] is True, str(res_short)[:120])


def main() -> int:
    test_var()
    test_drawdown()
    test_vol_beta_sharpe()
    test_concentration_sector()
    test_correlation_curve()
    test_full_assessment()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
