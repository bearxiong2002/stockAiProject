"""TechnicalEngine — 技术分析引擎（阶段 4.1）。

指标计算、信号检测与评分全部基于 pandas/numpy 实现，K 线输入为 DataFetcher
的契约列: date, open, close, high, low, volume, amount, amplitude, pct_change,
change, turnover（涨跌幅/换手率为百分数值）。缺测以 None/NaN 表达，不得补 0。

评分模型按 design.md 4.2.2: 趋势 0.35 + 震荡 0.25 + 通道 0.15 + 量价 0.25。
各子项分值与 design 表一致，组内求和后 clamp 到 ±100。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

MA_PERIODS = (5, 10, 20, 60, 120, 250)
EMA_PERIODS = (12, 26)
RSI_PERIODS = (6, 12, 24)

WEIGHTS = {"trend": 0.35, "oscillator": 0.25, "channel": 0.15, "volume": 0.25}


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _f(v) -> float | None:
    """契约数值 → float；缺测(NaN/None)保持 None，不补 0。"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def rating_of(score: float) -> str:
    """design 4.2.2 评级表（技术/基本面共用）。"""
    if score >= 60:
        return "强烈看多"
    if score >= 20:
        return "看多"
    if score > -20:
        return "中性"
    if score > -60:
        return "看空"
    return "强烈看空"


class TechnicalEngine:
    """技术指标 + 信号 + 评分。所有 calc_* 接受契约 K 线 DataFrame。"""

    # ------------------------------------------------------------------
    # 指标计算
    # ------------------------------------------------------------------

    def calc_ma(self, df: pd.DataFrame, periods=MA_PERIODS) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for n in periods:
            out[f"ma_{n}"] = df["close"].rolling(n, min_periods=n).mean().round(4)
        return out

    def calc_ema(self, df: pd.DataFrame, periods=EMA_PERIODS) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for n in periods:
            out[f"ema_{n}"] = df["close"].ewm(span=n, adjust=False).mean().round(4)
        return out

    def calc_macd(self, df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        out = pd.DataFrame(index=df.index)
        out["dif"] = (dif).round(4)
        out["dea"] = dea.round(4)
        out["macd_hist"] = ((dif - dea) * 2).round(4)  # A股惯例柱值 = 2×(DIF-DEA)
        return out

    def calc_kdj(self, df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
        low_n = df["low"].rolling(n, min_periods=1).min()
        high_n = df["high"].rolling(n, min_periods=1).max()
        denom = (high_n - low_n).replace(0, np.nan)
        rsv = ((df["close"] - low_n) / denom * 100).fillna(50.0)
        k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
        d = k.ewm(alpha=1 / m2, adjust=False).mean()
        out = pd.DataFrame(index=df.index)
        out["kdj_k"] = k.round(4)
        out["kdj_d"] = d.round(4)
        out["kdj_j"] = (3 * k - 2 * d).round(4)
        return out

    def calc_rsi(self, df: pd.DataFrame, periods=RSI_PERIODS) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        delta = df["close"].diff()
        up = delta.clip(lower=0)
        down = (-delta).clip(lower=0)
        for n in periods:
            # Wilder 平滑（EMA with alpha=1/n）
            avg_up = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
            avg_down = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
            rs = avg_up / avg_down.replace(0, np.nan)
            out[f"rsi_{n}"] = (100 - 100 / (1 + rs)).round(4)
            # 全下跌时 avg_up=0 → RSI=0；全上涨 avg_down=0 → RSI=100
            out.loc[avg_up == 0, f"rsi_{n}"] = 0.0
            out.loc[avg_down == 0, f"rsi_{n}"] = 100.0
        return out

    def calc_boll(self, df: pd.DataFrame, n=20, k=2) -> pd.DataFrame:
        mid = df["close"].rolling(n, min_periods=n).mean()
        std = df["close"].rolling(n, min_periods=n).std(ddof=0)
        out = pd.DataFrame(index=df.index)
        out["boll_mid"] = mid.round(4)
        out["boll_upper"] = (mid + k * std).round(4)
        out["boll_lower"] = (mid - k * std).round(4)
        return out

    def calc_wr(self, df: pd.DataFrame, n=14) -> pd.DataFrame:
        """威廉指标 %R = (Hn - C) / (Hn - Ln) × -100。

        取值 -100 ~ 0: 接近 0（价格收在区间高位）= 超买，接近 -100 = 超卖。
        design.md 4.2.1 表中"超买(<-80)/超卖(>-20)"与本公式相反，按公式
        的标准含义实现（超买 > -20、超卖 < -80）。
        """
        low_n = df["low"].rolling(n, min_periods=1).min()
        high_n = df["high"].rolling(n, min_periods=1).max()
        denom = (high_n - low_n).replace(0, np.nan)
        out = pd.DataFrame(index=df.index)
        out["wr"] = ((high_n - df["close"]) / denom * -100).fillna(-50.0).round(4)
        return out

    def calc_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        direction = np.sign(df["close"].diff().fillna(0.0))
        obv = (direction * df["volume"].astype(float)).cumsum()
        out = pd.DataFrame(index=df.index)
        out["obv"] = obv.round(2)
        return out

    def calc_volume_ma(self, df: pd.DataFrame, periods=(5, 10)) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        vol = df["volume"].astype(float)
        for n in periods:
            out[f"vol_ma_{n}"] = vol.rolling(n, min_periods=n).mean().round(2)
        # 量比: 当日成交量 / 过去5日均量
        out["volume_ratio"] = (vol / vol.rolling(5).mean().shift(1)).round(4)
        return out

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """全部指标按列合并到 K 线（indicators DataFrame，index 对齐）。"""
        parts = [self.calc_ma(df), self.calc_ema(df), self.calc_macd(df),
                 self.calc_kdj(df), self.calc_rsi(df), self.calc_boll(df),
                 self.calc_wr(df), self.calc_obv(df), self.calc_volume_ma(df)]
        out = df.copy()
        for p in parts:
            out = pd.concat([out, p], axis=1)
        return out

    # ------------------------------------------------------------------
    # 信号检测
    # ------------------------------------------------------------------

    def detect_ma_alignment(self, ind: pd.DataFrame, close: pd.Series) -> dict:
        """均线排列: 多头 / 空头 / 混合（按相邻对正确比例打分，缺失周期跳过）。"""
        vals = []
        for n in MA_PERIODS:
            col = f"ma_{n}"
            if col in ind.columns and pd.notna(ind[col].iloc[-1]):
                vals.append(float(ind[col].iloc[-1]))
        pairs_total = len(vals) - 1
        if pairs_total <= 0:
            return {"state": "insufficient", "score": 0.0, "detail": "均线数据不足"}
        bull = sum(1 for i in range(pairs_total) if vals[i] > vals[i + 1])
        p = bull / pairs_total
        score = _clamp(-80 + 160 * p, -80, 80)
        state = "bullish" if p >= 0.99 else ("bearish" if p == 0 else "mixed")
        return {"state": state, "score": round(score, 2),
                "detail": f"{'/'.join(str(n) for n in MA_PERIODS[:len(vals)])} "
                          f"多头排列对 {bull}/{pairs_total}"}

    def detect_cross(self, fast: pd.Series, slow: pd.Series,
                     recent: int = 5) -> dict:
        """快线/慢线交叉状态 + 最近一次交叉时间。

        state: golden_cross(最近发生) / death_cross(最近发生) /
               bullish_above(金叉后维持) / bearish_below(死叉后维持) / neutral
        """
        if fast is None or slow is None or len(fast) < 2:
            return {"state": "neutral", "crossed_at": None, "detail": "数据不足"}
        diff = (fast - slow).dropna()
        if len(diff) < 2:
            return {"state": "neutral", "crossed_at": None, "detail": "数据不足"}
        sign = np.sign(diff)
        crossed = sign.diff().fillna(0) != 0
        last_idx = diff.index[-1]
        recent_idx = diff.index[-recent:] if len(diff) >= recent else diff.index
        event = None
        for i in reversed(list(recent_idx)):
            if crossed.loc[i] and sign.loc[i] != 0:
                event = ("golden_cross" if sign.loc[i] > 0 else "death_cross", i)
                break
        above = sign.iloc[-1] > 0
        if event:
            return {"state": event[0], "crossed_at": str(event[1]),
                    "detail": f"最近 {recent} 日内发生"
                              f"{'金叉' if event[0] == 'golden_cross' else '死叉'}"}
        return {"state": "bullish_above" if above else "bearish_below",
                "crossed_at": None,
                "detail": "快线在慢线上方" if above else "快线在慢线下方"}

    def detect_divergence(self, price: pd.Series, indicator: pd.Series,
                          lookback: int = 60, segments: int = 3) -> dict:
        """简化背离检测: 将 lookback 窗口等分 segments 段，比较价格段极值与指标段极值。

        顶背离: 价格创近期新高而指标峰值降低；底背离: 价格创新低而指标谷值抬高。
        """
        if len(price) < lookback or len(indicator) < lookback:
            return {"type": None, "detail": "回看窗口不足"}
        p = price.iloc[-lookback:].reset_index(drop=True)
        v = indicator.iloc[-lookback:].reset_index(drop=True)
        size = max(lookback // segments, 5)
        seg_peaks, seg_troughs = [], []
        for i in range(segments):
            chunk = slice(i * size, (i + 1) * size)
            seg_peaks.append(float(p.iloc[chunk].max()))
            seg_troughs.append(float(p.iloc[chunk].min()))
        # v 已 reset_index：段内 idxmax/idxmin 返回的标签即全局位置
        peak_pos = [int(v.iloc[i * size:(i + 1) * size].idxmax())
                    for i in range(segments)]
        trough_pos = [int(v.iloc[i * size:(i + 1) * size].idxmin())
                      for i in range(segments)]
        seg_vpeaks = [float(v.iloc[pos]) for pos in peak_pos]
        seg_vtroughs = [float(v.iloc[pos]) for pos in trough_pos]
        # 只比较最近两段（价格条件）与第一段（旧基准），避免噪声
        price_new_high = seg_peaks[-1] >= seg_peaks[0]
        price_new_low = seg_troughs[-1] <= seg_troughs[0]
        top_div = price_new_high and seg_vpeaks[-1] < seg_vpeaks[0]
        bottom_div = price_new_low and seg_vtroughs[-1] > seg_vtroughs[0]
        if top_div:
            return {"type": "top_divergence",
                    "detail": f"价格新高中枢 {seg_peaks[-1]:.2f} vs {seg_peaks[0]:.2f}，指标峰值走低"}
        if bottom_div:
            return {"type": "bottom_divergence",
                    "detail": f"价格新低 {seg_troughs[-1]:.2f} vs {seg_troughs[0]:.2f}，指标谷值抬高"}
        return {"type": None, "detail": "无背离"}

    def detect_overbought_oversold(self, value: float, upper: float,
                                   lower: float) -> dict:
        """通用超买/超卖判断（value >= upper 超买 / value <= lower 超卖）。"""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return {"state": "unknown", "detail": "数值缺失"}
        if value >= upper:
            return {"state": "overbought", "detail": f"{value:.2f} ≥ {upper}"}
        if value <= lower:
            return {"state": "oversold", "detail": f"{value:.2f} ≤ {lower}"}
        return {"state": "neutral", "detail": f"{value:.2f}"}

    def detect_volume_price(self, kline: pd.DataFrame, ind: pd.DataFrame) -> dict:
        """量价配合: 涨+放量 / 涨+缩量 / 跌+放量 / 跌+缩量。"""
        if kline.empty or len(kline) < 6:
            return {"type": "unknown", "detail": "数据不足"}
        pct = kline["pct_change"].iloc[-1]
        vol_ratio = _f(ind["volume_ratio"].iloc[-1]) if "volume_ratio" in ind else None
        if pct is None or vol_ratio is None:
            return {"type": "unknown", "detail": "数值缺失"}
        up = pct > 0
        heavy = vol_ratio >= 1.5
        dry = vol_ratio < 0.8
        if up and heavy:
            t = "up_with_volume"
        elif up and dry:
            t = "up_on_dry"
        elif not up and heavy:
            t = "down_with_volume"
        elif not up and dry:
            t = "down_on_dry"
        else:
            t = "balanced"
        return {"type": t, "detail": f"涨跌幅 {pct:+.2f}% 量比 {vol_ratio:.2f}"}

    # ------------------------------------------------------------------
    # 评分
    # ------------------------------------------------------------------

    def score_trend(self, kline: pd.DataFrame, ind: pd.DataFrame) -> tuple[float, list[dict]]:
        close = kline["close"]
        signals: list[dict] = []
        align = self.detect_ma_alignment(ind, close)
        signals.append({"indicator": "MA排列", "value": align["state"],
                        "signal": align["detail"], "direction": align["state"]})
        macd = self.detect_cross(ind["dif"], ind["dea"])
        hist = ind["macd_hist"]
        base = 40 if macd["state"] in ("golden_cross", "bullish_above") else -40
        momentum = 0
        if len(hist) >= 2 and pd.notna(hist.iloc[-1]) and pd.notna(hist.iloc[-2]):
            if base > 0 and hist.iloc[-1] >= hist.iloc[-2]:
                momentum = 20
            elif base < 0 and hist.iloc[-1] < hist.iloc[-2]:
                momentum = -20
        divergence = self.detect_divergence(close, ind["dif"])
        div_score = 0
        if divergence["type"] == "top_divergence":
            div_score = -60
        elif divergence["type"] == "bottom_divergence":
            div_score = 40  # design 未列底背离分值，按顶背离对称取 +40
        event_score = (40 if macd["state"] == "golden_cross"
                       else -40 if macd["state"] == "death_cross" else 0)
        signals.append({"indicator": "MACD", "value": f'DIF={_f(ind["dif"].iloc[-1]):.3f} DEA={_f(ind["dea"].iloc[-1]):.3f}'
                        if _f(ind["dif"].iloc[-1]) is not None else None,
                        "signal": macd["state"],
                        "direction": "up" if base + momentum >= 0 else "down"})
        if div_score:
            signals.append({"indicator": "MACD背离", "value": divergence["type"],
                            "signal": divergence["detail"],
                            "direction": "up" if div_score > 0 else "down"})
        ma250 = _f(ind["ma_250"].iloc[-1]) if "ma_250" in ind else None
        last_close = _f(close.iloc[-1])
        ma250_score = 0
        if ma250 is not None and last_close is not None:
            ma250_score = 20 if last_close > ma250 else -20
            signals.append({"indicator": "MA250", "value": ma250,
                            "signal": "站上年线" if ma250_score > 0 else "跌破年线",
                            "direction": "up" if ma250_score > 0 else "down"})
        score = _clamp(align["score"] + base + momentum + div_score
                       + event_score + ma250_score)
        return round(score, 2), signals

    def score_oscillator(self, kline: pd.DataFrame, ind: pd.DataFrame) -> tuple[float, list[dict]]:
        signals: list[dict] = []
        total = 0.0
        kdj_cross = self.detect_cross(ind["kdj_k"], ind["kdj_d"])
        j_now = _f(ind["kdj_j"].iloc[-1])
        if j_now is not None:
            if j_now < 0:
                total += 50
                signals.append({"indicator": "KDJ-J", "value": j_now,
                                "signal": "J<0 超卖区", "direction": "up"})
            elif j_now > 100:
                total -= 50
                signals.append({"indicator": "KDJ-J", "value": j_now,
                                "signal": "J>100 超买区", "direction": "down"})
            if kdj_cross["state"] == "golden_cross":
                total += 30
                signals.append({"indicator": "KDJ", "value": f"K={_f(ind['kdj_k'].iloc[-1]):.1f} D={_f(ind['kdj_d'].iloc[-1]):.1f}",
                                "signal": "金叉", "direction": "up"})
            elif kdj_cross["state"] == "death_cross":
                total -= 30
                signals.append({"indicator": "KDJ", "value": f"K={_f(ind['kdj_k'].iloc[-1]):.1f} D={_f(ind['kdj_d'].iloc[-1]):.1f}",
                                "signal": "死叉", "direction": "down"})
        rsi6 = _f(ind["rsi_6"].iloc[-1]) if "rsi_6" in ind else None
        if rsi6 is not None:
            ob = self.detect_overbought_oversold(rsi6, 70, 30)
            if ob["state"] == "oversold":
                total += 40
                signals.append({"indicator": "RSI6", "value": rsi6,
                                "signal": "<30 超卖", "direction": "up"})
            elif ob["state"] == "overbought":
                total -= 40
                signals.append({"indicator": "RSI6", "value": rsi6,
                                "signal": ">70 超买", "direction": "down"})
            div = self.detect_divergence(kline["close"], ind["rsi_6"])
            if div["type"] == "top_divergence":
                total -= 20
                signals.append({"indicator": "RSI背离", "value": rsi6,
                                "signal": div["detail"], "direction": "down"})
            elif div["type"] == "bottom_divergence":
                total += 20
                signals.append({"indicator": "RSI背离", "value": rsi6,
                                "signal": div["detail"], "direction": "up"})
        wr = _f(ind["wr"].iloc[-1])
        if wr is not None:
            if wr > -20:  # 收在区间高位 = 超买
                total -= 10
                signals.append({"indicator": "WR", "value": wr,
                                "signal": "超买区", "direction": "down"})
            elif wr < -80:  # 收在区间低位 = 超卖
                total += 10
                signals.append({"indicator": "WR", "value": wr,
                                "signal": "超卖区", "direction": "up"})
        return round(_clamp(total), 2), signals

    def score_channel(self, kline: pd.DataFrame, ind: pd.DataFrame) -> tuple[float, list[dict]]:
        signals: list[dict] = []
        total = 0.0
        close = _f(kline["close"].iloc[-1])
        upper = _f(ind["boll_upper"].iloc[-1])
        lower = _f(ind["boll_lower"].iloc[-1])
        mid = _f(ind["boll_mid"].iloc[-1])
        if close is not None and upper is not None and lower is not None and mid is not None:
            if close <= lower * 1.01:
                total += 30
                signals.append({"indicator": "BOLL", "value": close,
                                "signal": "触及下轨（超卖）", "direction": "up"})
            elif close >= upper * 0.99:
                total -= 30
                signals.append({"indicator": "BOLL", "value": close,
                                "signal": "触及上轨（超买）", "direction": "down"})
            # 开口: 带宽最近 5 日变化
            width = (ind["boll_upper"] - ind["boll_lower"]) / ind["boll_mid"]
            w_now, w_prev = _f(width.iloc[-1]), _f(width.iloc[-6]) if len(width) >= 6 else None
            if w_now is not None and w_prev is not None:
                if w_now > w_prev:
                    total += 20
                    signals.append({"indicator": "BOLL带宽", "value": round(w_now, 4),
                                    "signal": "开口扩大", "direction": "up"})
                else:
                    total -= 20
                    signals.append({"indicator": "BOLL带宽", "value": round(w_now, 4),
                                    "signal": "开口收窄", "direction": "down"})
            # 中轨趋势: 中轨 5 日变化
            mid_prev = _f(ind["boll_mid"].iloc[-6]) if len(ind["boll_mid"]) >= 6 else None
            if mid_prev is not None:
                if mid > mid_prev:
                    total += 10
                    signals.append({"indicator": "BOLL中轨", "value": mid,
                                    "signal": "向上", "direction": "up"})
                else:
                    total -= 10
                    signals.append({"indicator": "BOLL中轨", "value": mid,
                                    "signal": "向下", "direction": "down"})
        return round(_clamp(total), 2), signals

    def score_volume(self, kline: pd.DataFrame, ind: pd.DataFrame) -> tuple[float, list[dict]]:
        signals: list[dict] = []
        total = 0.0
        vp = self.detect_volume_price(kline, ind)
        vp_score = {"up_with_volume": 40, "up_on_dry": -10,
                    "down_with_volume": -40, "down_on_dry": 10}.get(vp["type"], 0)
        total += vp_score
        if vp_score:
            signals.append({"indicator": "量价配合", "value": vp["type"],
                            "signal": vp["detail"],
                            "direction": "up" if vp_score > 0 else "down"})
        obv = ind.get("obv")
        if obv is not None and len(obv) >= 20:
            obv_win = obv.iloc[-20:].dropna()
            if len(obv_win) >= 20:
                slope = float(np.polyfit(range(len(obv_win)), obv_win.values, 1)[0])
                total += 20 if slope > 0 else -20
                signals.append({"indicator": "OBV", "value": round(_f(obv.iloc[-1]) or 0, 2),
                                "signal": "20日能量趋势向上" if slope > 0 else "20日能量趋势向下",
                                "direction": "up" if slope > 0 else "down"})
        turnover = kline["turnover"]
        if turnover is not None and len(turnover) >= 21 and pd.notna(turnover.iloc[-1]):
            t = _f(turnover.iloc[-1])
            t_ma = _f(turnover.iloc[-21:-1].mean())
            if t is not None and t_ma is not None and t_ma > 0 and t > t_ma * 3:
                up = _f(kline["pct_change"].iloc[-1]) is not None and kline["pct_change"].iloc[-1] > 0
                total += 20 if up else -20
                signals.append({"indicator": "换手率", "value": t,
                                "signal": "异常高换手", "direction": "up" if up else "down"})
        return round(_clamp(total), 2), signals

    def get_technical_score(self, kline: pd.DataFrame,
                            ind: pd.DataFrame | None = None) -> dict:
        """技术总分 = 趋势×0.35 + 震荡×0.25 + 通道×0.15 + 量价×0.25。

        ind 可传入预计算的 compute_all() 结果，同一请求不再重复算指标。
        数据不足（K 线 < 60 行）时 incomplete=True、score=None，不产出评级。
        """
        if kline is None or len(kline) < 60:
            return {"score": None, "rating": None, "incomplete": True,
                    "components": {}, "signals": [],
                    "summary": "K线数据不足，无法进行技术分析",
                    "weights": WEIGHTS}
        if ind is None:
            ind = self.compute_all(kline)
        t_score, t_sig = self.score_trend(kline, ind)
        o_score, o_sig = self.score_oscillator(kline, ind)
        c_score, c_sig = self.score_channel(kline, ind)
        v_score, v_sig = self.score_volume(kline, ind)
        score = round(_clamp(t_score * WEIGHTS["trend"] + o_score * WEIGHTS["oscillator"]
                             + c_score * WEIGHTS["channel"] + v_score * WEIGHTS["volume"]), 2)
        return {
            "score": score,
            "rating": rating_of(score),
            "components": {
                "trend": {"score": t_score, "weight": WEIGHTS["trend"], "signals": t_sig},
                "oscillator": {"score": o_score, "weight": WEIGHTS["oscillator"], "signals": o_sig},
                "channel": {"score": c_score, "weight": WEIGHTS["channel"], "signals": c_sig},
                "volume": {"score": v_score, "weight": WEIGHTS["volume"], "signals": v_sig},
            },
            "signals": t_sig + o_sig + c_sig + v_sig,
            "weights": WEIGHTS,
            "incomplete": False,
        }

    # ------------------------------------------------------------------
    # 图表用指标序列（design 6.2 indicator_data）
    # ------------------------------------------------------------------

    def indicator_series(self, kline: pd.DataFrame,
                         ind: pd.DataFrame | None = None) -> dict:
        """报告 JSON 的 indicator_data: 仅前端画图所需序列（不含全量合并表）。

        ind 可传入预计算结果（与 get_technical_score 共享同一次 compute_all）。
        """
        if ind is None:
            ind = self.compute_all(kline)

        def series(col: str) -> list:
            return [None if (v is None or pd.isna(v)) else round(float(v), 4)
                    for v in ind[col]]
        out: dict[str, Any] = {"dates": list(kline["date"])}
        for n in (5, 10, 20, 60):
            out.setdefault("ma", {})[f"ma_{n}"] = series(f"ma_{n}")
        out["macd"] = {k: series(k) for k in ("dif", "dea", "macd_hist")}
        out["kdj"] = {k: series(k) for k in ("kdj_k", "kdj_d", "kdj_j")}
        out["boll"] = {k: series(k) for k in ("boll_mid", "boll_upper", "boll_lower")}
        out["volume"] = {"volume": [round(float(v), 2) for v in kline["volume"]],
                         "vol_ma_5": series("vol_ma_5"), "vol_ma_10": series("vol_ma_10")}
        return out
