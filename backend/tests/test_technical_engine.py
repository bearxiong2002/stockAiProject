"""阶段 4.1/4.2/4.3 离线正确性测试（不联网、不需要真实 Key）。

run: .venv/bin/python tests/test_technical_engine.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

from services.technical import TechnicalEngine, rating_of
from services.fundamental import FundamentalEngine
from services.scorer import ScoringEngine

E = TechnicalEngine()
F = FundamentalEngine()
S = ScoringEngine()
PASS = FAIL = 0
TOL = 1e-3  # 引擎输出统一 round(4)


def check(name: str, cond, detail="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def kline(close: list[float], vol: float = 1e6, turnover: float = 1.0,
          pct: list[float] | None = None) -> pd.DataFrame:
    c = pd.Series(close, dtype=float)
    return pd.DataFrame({
        "date": [f"d{i:04d}" for i in range(len(c))],
        "open": c.shift(1).fillna(c.iloc[0]),
        "close": c, "high": c + 0.5, "low": c - 0.5,
        "volume": float(vol), "amount": 1e9, "amplitude": 2.0,
        "pct_change": (pct if pct is not None else c.pct_change().fillna(0) * 100),
        "change": c.diff().fillna(0), "turnover": turnover,
    })


def test_ma_ema():
    print("\n[MA / EMA 手算对照]")
    df = kline([1, 2, 3, 4, 5, 6, 7])
    ma = E.calc_ma(df, periods=(2, 3))
    check("MA2 终值 6.5", abs(ma["ma_2"].iloc[-1] - 6.5) < TOL, str(ma["ma_2"].tolist()))
    check("MA2 首行缺测(窗口不足)", bool(pd.isna(ma["ma_2"].iloc[0])))
    check("MA3 前两行缺测", bool(pd.isna(ma["ma_3"].iloc[0])) and bool(pd.isna(ma["ma_3"].iloc[1])))
    check("MA3 第三行=2.0", abs(ma["ma_3"].iloc[2] - 2.0) < TOL)
    ema = E.calc_ema(df, periods=(3,))
    vals = [1.0]
    for x in (2, 3, 4, 5, 6, 7):
        vals.append(2 / 4 * x + (1 - 2 / 4) * vals[-1])
    check("EMA3 递推一致", abs(ema["ema_3"].iloc[-1] - vals[-1]) < TOL,
          f"{ema['ema_3'].iloc[-1]} vs {vals[-1]}")


def test_macd_kdj_rsi():
    print("\n[MACD / KDJ / RSI / BOLL / WR / OBV 已知值]")
    close = (np.linspace(10, 20, 100) + np.sin(np.arange(100)) * 0.3).tolist()
    df = kline(close)
    macd = E.calc_macd(df)
    dif = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    check("DIF=EMA12-EMA26", abs(macd["dif"].iloc[-1] - dif.iloc[-1]) < TOL)
    check("DEA=EMA9(DIF)", abs(macd["dea"].iloc[-1] - dea.iloc[-1]) < TOL)
    check("hist=2×(DIF-DEA)",
          abs(macd["macd_hist"].iloc[-1] - 2 * (dif.iloc[-1] - dea.iloc[-1])) < TOL)
    kdj = E.calc_kdj(df, n=9)
    low9 = df["low"].rolling(9, min_periods=1).min()
    high9 = df["high"].rolling(9, min_periods=1).max()
    rsv = (df["close"] - low9) / (high9 - low9) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    check("KDJ K=RSV平滑", abs(kdj["kdj_k"].iloc[-1] - k.iloc[-1]) < TOL,
          f"{kdj['kdj_k'].iloc[-1]} vs {k.iloc[-1]}")
    check("KDJ J=3K-2D",
          abs(kdj["kdj_j"].iloc[-1] - (3 * k.iloc[-1] - 2 * d.iloc[-1])) < TOL)
    check("RSI 单调上涨=100",
          abs(E.calc_rsi(kline(list(np.linspace(1, 2, 60))), periods=(6,))["rsi_6"].iloc[-1] - 100) < TOL)
    check("RSI 单调下跌=0",
          abs(E.calc_rsi(kline(list(np.linspace(2, 1, 60))), periods=(6,))["rsi_6"].iloc[-1] - 0) < TOL)
    rsi = E.calc_rsi(df, periods=(6,))
    delta = df["close"].diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 6, adjust=False, min_periods=6).mean()
    dn = (-delta).clip(lower=0).ewm(alpha=1 / 6, adjust=False, min_periods=6).mean()
    check("RSI6 与 Wilder 公式一致",
          abs(rsi["rsi_6"].iloc[-1] - (100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))) < TOL,
          f"{rsi['rsi_6'].iloc[-1]}")
    boll = E.calc_boll(df, n=20, k=2)
    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std(ddof=0)
    check("BOLL 中轨=MA20", abs(boll["boll_mid"].iloc[-1] - mid.iloc[-1]) < TOL)
    check("BOLL 上轨=中轨+2σ",
          abs(boll["boll_upper"].iloc[-1] - (mid.iloc[-1] + 2 * std.iloc[-1])) < TOL)
    wr = E.calc_wr(df, n=14)
    h14 = df["high"].rolling(14, min_periods=1).max()
    l14 = df["low"].rolling(14, min_periods=1).min()
    check("WR=(Hn-C)/(Hn-Ln)×-100",
          abs(wr["wr"].iloc[-1] - (h14.iloc[-1] - df["close"].iloc[-1])
              / (h14.iloc[-1] - l14.iloc[-1]) * -100) < TOL,
          f"{wr['wr'].iloc[-1]}")
    w_up = E.calc_wr(kline(list(np.linspace(1, 10, 40))))["wr"].iloc[-1]
    w_dn = E.calc_wr(kline(list(np.linspace(10, 1, 40))))["wr"].iloc[-1]
    check("WR 上涨收高位(>-20 超买) / 下跌收低位(<-80 超卖)",
          w_up > -20 and w_dn < -80, f"up={w_up} dn={w_dn}")
    obv = E.calc_obv(kline(list(np.linspace(1, 10, 40))))
    check("OBV 连涨累积为正", obv["obv"].iloc[-1] > 0)
    obv_dn = E.calc_obv(kline(list(np.linspace(10, 1, 40))))
    check("OBV 连跌累积为负", obv_dn["obv"].iloc[-1] < 0)


def test_signals():
    print("\n[信号检测: 金叉/死叉/超买超卖/量价]")
    c = E.detect_cross(pd.Series([1, 1, 1, 3, 3, 3], dtype=float),
                       pd.Series([2, 2, 2, 2, 2, 2], dtype=float))
    check("金叉检测", c["state"] == "golden_cross", str(c))
    c2 = E.detect_cross(pd.Series([3, 3, 1, 1, 1, 1], dtype=float),
                        pd.Series([2, 2, 2, 2, 2, 2], dtype=float))
    check("死叉检测", c2["state"] == "death_cross", str(c2))
    c3 = E.detect_cross(pd.Series([3, 3, 3, 3], dtype=float),
                        pd.Series([2, 2, 2, 2], dtype=float))
    check("金叉后维持", c3["state"] == "bullish_above", str(c3))
    check("RSI 超买", E.detect_overbought_oversold(75, 70, 30)["state"] == "overbought")
    check("RSI 超卖", E.detect_overbought_oversold(25, 70, 30)["state"] == "oversold")
    vp = E.detect_volume_price(
        kline([10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
              pct=[0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 2.0]),
        pd.DataFrame({"volume_ratio": [1.0] * 7 + [2.0]}))
    check("涨+放量", vp["type"] == "up_with_volume", str(vp))
    vp2 = E.detect_volume_price(
        kline([10.7, 10.6, 10.5, 10.4, 10.3, 10.2, 10.1, 10.0],
              pct=[-0.1] * 7 + [-2.0]),
        pd.DataFrame({"volume_ratio": [1.0] * 7 + [0.5]}))
    check("跌+缩量", vp2["type"] == "down_on_dry", str(vp2))
    vp3 = E.detect_volume_price(
        kline([10.7, 10.6, 10.5, 10.4, 10.3, 10.2, 10.1, 10.0],
              pct=[-0.1] * 7 + [-2.0]),
        pd.DataFrame({"volume_ratio": [1.0] * 7 + [2.0]}))
    check("跌+放量", vp3["type"] == "down_with_volume", str(vp3))


def test_scoring_direction():
    print("\n[技术评分方向性]")
    n = 300
    dates = [f"d{i:04d}" for i in range(n)]

    def mk(close_arr):
        c = pd.Series(close_arr, dtype=float)
        return pd.DataFrame({"date": dates, "open": c - 0.2, "close": c,
                             "high": c + 0.4, "low": c - 0.4,
                             "volume": 1e6, "amount": 1e9, "amplitude": 2.0,
                             "pct_change": c.pct_change().fillna(0) * 100,
                             "change": c.diff().fillna(0), "turnover": 1.0})

    up = mk(np.linspace(10, 25, n) * (1 + 0.005 * np.sin(np.arange(n))))
    # 温和阴跌（≈30天-5%，RSI 不触发超卖）→ design 语义的典型看空样本;
    # 注: 深跌超卖时震荡分按 design 会转正（超卖=反弹机会），慢熊总分趋近中性
    down = mk(np.linspace(25, 23.5, n) * (1 + 0.003 * np.sin(np.arange(n))))
    r_up = E.get_technical_score(up)
    r_dn = E.get_technical_score(down)
    check("上涨→正分", r_up["score"] > 0, f"{r_up['score']} {r_up['rating']}")
    check("下跌→负分", r_dn["score"] < 0, f"{r_dn['score']} {r_dn['rating']}")
    check("上涨强于下跌", r_up["score"] > r_dn["score"])
    r_short = E.get_technical_score(up.head(40))
    check("K线<60行→不产出评级", r_short["incomplete"] and r_short["score"] is None)
    check("评级映射", rating_of(70) == "强烈看多" and rating_of(30) == "看多"
          and rating_of(0) == "中性" and rating_of(-40) == "看空"
          and rating_of(-80) == "强烈看空")


def test_fundamental():
    print("\n[基本面评分]")
    info_good = {"pe": 10.0, "pb": 1.5, "ps": 1.0, "dividend_yield": 3.5}
    fin_good = {
        "industry_pe_pb": {"pe_median": 20.0, "pb_median": 2.5},
        "fina_indicator": pd.DataFrame({
            "roe": [22.0], "revenue_growth": [35.0], "profit_growth": [40.0],
            "debt_ratio": [30.0], "current_ratio": [2.5], "gross_margin": [55.0]}),
        "income": pd.DataFrame({"REPORT_DATE": ["2026-06-30"], "NETPROFIT": [100.0]}),
        "cashflow": pd.DataFrame({"REPORT_DATE": ["2026-06-30"], "NETCASH_OPERATE": [120.0]}),
    }
    r_good = F.get_fundamental_score(info_good, fin_good)
    check("高ROE低PE→正分", r_good["score"] > 0, f"{r_good['score']}")
    check("评级看多以上", r_good["rating"] in ("看多", "强烈看多"), r_good["rating"])
    info_bad = {"pe": 80.0, "pb": 12.0, "ps": 15.0, "dividend_yield": 0.2}
    fin_bad = {
        "industry_pe_pb": {"pe_median": 20.0, "pb_median": 2.5},
        "fina_indicator": pd.DataFrame({
            "roe": [3.0], "revenue_growth": [-10.0], "profit_growth": [-15.0],
            "debt_ratio": [80.0], "current_ratio": [0.6], "gross_margin": [20.0]}),
        "income": pd.DataFrame({"REPORT_DATE": ["2026-06-30"], "NETPROFIT": [100.0]}),
        "cashflow": pd.DataFrame({"REPORT_DATE": ["2026-06-30"], "NETCASH_OPERATE": [30.0]}),
    }
    r_bad = F.get_fundamental_score(info_bad, fin_bad)
    check("高PE高负债→负分", r_bad["score"] < 0, f"{r_bad['score']}")
    r_partial = F.get_fundamental_score(
        {"pe": 10.0, "pb": 1.5},
        {"industry_pe_pb": {"pe_median": 20.0, "pb_median": 2.5},
         "fina_indicator": None})
    check("仅估值数据→估值为正", r_partial["valuation"]["score"] > 0,
          str(r_partial["valuation"]))
    check("缺财务指标→incomplete", r_partial["incomplete"] is True)
    r_no_div = F.get_fundamental_score(
        {"pe": 10.0, "pb": 1.5, "ps": 1.0},
        {"industry_pe_pb": {"pe_median": 20.0, "pb_median": 2.5}})
    check("缺股息率→满分收缩85", r_no_div["valuation"]["max_possible"] == 85,
          str(r_no_div["valuation"]["max_possible"]))


def test_scoring_engine():
    print("\n[综合评分与评级映射]")
    cases = [(80, "★★★★★", "强烈推荐"), (45, "★★★★", "推荐"),
             (20, "★★★", "谨慎推荐"), (0, "★★", "中性"),
             (-25, "★", "不推荐"), (-80, "卖出", "建议清仓")]
    for score, level, label in cases:
        r = S.calculate_rating(score, score, score)
        check(f"{score:+d}→{level}", r["level"] == level and r["label"] == label,
              str(r))
    check("无AI 50/50 权重(60+20)/2=40",
          S.calculate_rating(60, 20)["score"] == 40.0)
    check("有AI 35/35/30: 60×.35+20×.35+0=28",
          S.calculate_rating(60, 20, 0)["score"] == 28.0)
    r_none = S.calculate_rating(None, 50)
    check("缺分→无评级", r_none["score"] is None and r_none["level"] is None)


def main() -> int:
    test_ma_ema()
    test_macd_kdj_rsi()
    test_signals()
    test_scoring_direction()
    test_fundamental()
    test_scoring_engine()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
