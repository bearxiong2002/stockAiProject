"""FundamentalEngine — 基本面分析引擎（阶段 4.2）。

评分模型按 design.md 4.3：估值 0.30 + 成长 0.40 + 健康 0.30。
- 估值/成长原始分满分 ±100；健康度满分 ±60 → 归一化 ×100/60。
- 指标缺失时该子项跳过（不按 0 评分），按"实际可用满分"归一化。
- 估值对比基准为申万一级行业中位数（get_industry_pe_pb）。
"""
from __future__ import annotations

import math

WEIGHTS = {"valuation": 0.30, "growth": 0.40, "health": 0.30}


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else None if math.isinf(x) else x


def _band_score(value: float | None, bands: list[tuple[float, float, int]]) -> int | None:
    """按 (下界, 上界, 分值) 的半开区间分档；value 在任何区间外返回 None。"""
    if value is None:
        return None
    for lo, hi, score in bands:
        if lo <= value < hi:
            return score
    return None


def _ratio_band(x: float | None, base: float | None,
                bands: list[tuple[float, float, int]]) -> tuple[int | None, float | None]:
    """value/base 相对倍数分档；任一缺测 → (None, None)。"""
    if x is None or base is None or base <= 0:
        return None, None
    ratio = x / base
    return _band_score(ratio, bands), round(ratio, 4)


# design 4.3.1 相对行业中位数的分档（PE/PB/PS 共用，按各自满分缩放）
PE_BANDS = [(0, 0.7, 40), (0.7, 1.0, 20), (1.0, 1.5, 0),
            (1.5, 3.0, -20), (3.0, math.inf, -40)]


def _scaled(bands: list[tuple[float, float, int]], k: float):
    return [(lo, hi, round(s * k)) for lo, hi, s in bands]


class FundamentalEngine:
    """基本面评分: score_valuation / score_growth / score_health + 总分。"""

    def score_valuation(self, stock_info: dict, financial_data: dict) -> tuple[float, dict]:
        """估值得分（满分 ±100；行业中位缺失的项跳过并收缩满分）。"""
        items: list[dict] = []
        total, max_possible = 0, 0
        pe = _f(stock_info.get("pe"))
        pb = _f(stock_info.get("pb"))
        ps = _f(stock_info.get("ps"))
        div_yield = _f(stock_info.get("dividend_yield"))
        ind = financial_data.get("industry_pe_pb") or {}
        ind_pe = _f(ind.get("pe_median"))
        ind_pb = _f(ind.get("pb_median"))

        if pe is not None and pe > 0:
            if ind_pe:
                s, ratio = _ratio_band(pe, ind_pe, PE_BANDS)
                max_possible += 40
            else:  # 无行业中位: 用绝对档（A股全市场中位经验值 ~25）
                ratio = None
                s = _band_score(pe, [(0, 10, 40), (10, 20, 20), (20, 35, 0),
                                     (35, 60, -20), (60, math.inf, -40)])
                max_possible += 40
            total += s or 0
            items.append({"name": "PE(TTM)", "value": pe, "industry_median": ind_pe,
                          "ratio": ratio, "score": s or 0})
        if pb is not None and pb > 0:
            if ind_pb:
                s, ratio = _ratio_band(pb, ind_pb, _scaled(PE_BANDS, 30 / 40))
                max_possible += 30
            else:
                ratio = None
                s = _band_score(pb, [(0, 1.5, 30), (1.5, 2.5, 15), (2.5, 4, 0),
                                     (4, 8, -15), (8, math.inf, -30)])
                max_possible += 30
            total += s or 0
            items.append({"name": "PB", "value": pb, "industry_median": ind_pb,
                          "ratio": ratio, "score": s or 0})
        if ps is not None and ps > 0:
            # PS 无行业对比数据: 绝对档（低 PS 反映营收定价）
            s = _band_score(ps, [(0, 1, 15), (1, 2, 7), (2, 5, 0),
                                 (5, 10, -7), (10, math.inf, -15)])
            total += s or 0
            max_possible += 15
            items.append({"name": "PS", "value": ps, "industry_median": None,
                          "ratio": None, "score": s or 0})
        if div_yield is not None:
            s = _band_score(div_yield, [(3.0, math.inf, 15), (2.0, 3.0, 10),
                                        (1.0, 2.0, 5), (0, 1.0, 0)])
            total += s or 0
            max_possible += 15
            items.append({"name": "股息率", "value": div_yield,
                          "industry_median": None, "ratio": None, "score": s or 0})
        score = round(_clamp(total / max_possible * 100 if max_possible else 0), 2)
        return score, {"items": items, "max_possible": max_possible}

    def score_growth(self, financial_data: dict) -> tuple[float, dict]:
        """成长性得分（满分 ±100）。financial_data 含 fina_indicator(最近8期)。"""
        fin = financial_data.get("fina_indicator")
        items: list[dict] = []
        total, max_possible = 0, 0
        rev = prof = roe = None
        if fin is not None and len(fin):
            rev = _f(fin.iloc[-1].get("revenue_growth"))
            prof = _f(fin.iloc[-1].get("profit_growth"))
            roe = _f(fin.iloc[-1].get("roe"))
        for name, v in (("营收增长率(YoY)", rev), ("净利润增长率(YoY)", prof)):
            max_possible += 50  # design ±30 区间 + 缺失跳过按满分折算
            if v is None:
                items.append({"name": name, "value": None, "score": None})
                max_possible -= 50  # 缺失 → 不计满分也不计 0 分
                continue
            s = _band_score(v, [(30.0, math.inf, 30), (15.0, 30.0, 20), (5.0, 15.0, 10),
                                (0.0, 5.0, 0), (-math.inf, 0.0, -20)])
            total += s or 0
            items.append({"name": name, "value": v, "score": s or 0})
        if roe is not None:
            max_possible += 30
            s = _band_score(roe, [(20.0, math.inf, 30), (15.0, 20.0, 20),
                                  (10.0, 15.0, 10), (5.0, 10.0, 0),
                                  (-math.inf, 5.0, -10)])
            total += s or 0
            items.append({"name": "ROE", "value": roe, "score": s or 0})
        else:
            items.append({"name": "ROE", "value": None, "score": None})
        # 连续增长季度数（最近 4 期 profit_growth 均有效）
        streak_score = 0
        if fin is not None and len(fin) >= 4:
            streak = 0
            for v in reversed(fin["profit_growth"].tolist()):
                x = _f(v)
                if x is None:
                    break
                if x > 0:
                    streak += 1
                else:
                    break
            streak_score = 10 if streak >= 4 else (5 if streak >= 2 else 0)
            total += streak_score
            items.append({"name": "连续增长季数", "value": streak, "score": streak_score})
            max_possible += 10
        score = round(_clamp(total / max_possible * 100 if max_possible else 0), 2)
        return score, {"items": items, "max_possible": max_possible}

    def score_health(self, financial_data: dict) -> tuple[float, dict]:
        """财务健康度（原始满分 ±60 → 归一化 ±100）。"""
        fin = financial_data.get("fina_indicator")
        income = financial_data.get("income")
        cashflow = financial_data.get("cashflow")
        items: list[dict] = []
        total = 0
        max_possible = 60

        debt = cur = gross = None
        if fin is not None and len(fin):
            debt = _f(fin.iloc[-1].get("debt_ratio"))
            cur = _f(fin.iloc[-1].get("current_ratio"))
            gross = _f(fin.iloc[-1].get("gross_margin"))
        if debt is not None:
            s = _band_score(debt, [(0, 40, 20), (40, 60, 10), (60, 70, 0),
                                   (70, math.inf, -20)]) or 0
            total += s
            items.append({"name": "资产负债率", "value": debt, "score": s})
        else:
            items.append({"name": "资产负债率", "value": None, "score": None})
        if cur is not None:
            s = _band_score(cur, [(2.0, math.inf, 15), (1.5, 2.0, 10),
                                  (1.0, 1.5, 0), (0, 1.0, -15)]) or 0
            total += s
            items.append({"name": "流动比率", "value": cur, "score": s})
        else:
            items.append({"name": "流动比率", "value": None, "score": None})
        if income is not None and cashflow is not None and len(income) and len(cashflow):
            # 同报告期匹配: 取两表最近的共同 REPORT_DATE
            inc_dates = set(income["REPORT_DATE"].dropna().tolist())
            cf = cashflow[cashflow["REPORT_DATE"].isin(inc_dates)]
            if len(cf):
                c_row = cf.iloc[-1]
                i_row = income[income["REPORT_DATE"] == c_row["REPORT_DATE"]].iloc[0]
                profit = _f(i_row.get("NETPROFIT"))
                ocf = _f(c_row.get("NETCASH_OPERATE"))
                if profit is not None and ocf is not None and profit != 0:
                    ratio = ocf / profit
                    s = _band_score(ratio, [(1.0, math.inf, 15), (0.7, 1.0, 5),
                                            (-math.inf, 0.7, -10)]) or 0
                    total += s
                    items.append({"name": "经营现金流/净利润", "value": round(ratio, 4),
                                  "score": s})
                else:
                    items.append({"name": "经营现金流/净利润", "value": None, "score": None})
            else:
                items.append({"name": "经营现金流/净利润", "value": None, "score": None})
        else:
            items.append({"name": "经营现金流/净利润", "value": None, "score": None})
        if gross is not None:
            s = _band_score(gross, [(50.0, math.inf, 10), (30.0, 50.0, 5),
                                    (0, 30.0, 0)]) or 0
            # 下滑趋势: 毛利率较上一期下降 > 2pp
            if fin is not None and len(fin) >= 2:
                prev = _f(fin.iloc[-2].get("gross_margin"))
                if prev is not None and gross < prev - 2:
                    s -= 10
                    items.append({"name": "毛利率", "value": gross,
                                  "score": s, "note": "较上期下降超 2pp"})
                else:
                    items.append({"name": "毛利率", "value": gross, "score": s})
            else:
                items.append({"name": "毛利率", "value": gross, "score": s})
            total += s
        else:
            items.append({"name": "毛利率", "value": None, "score": None})
        score = round(_clamp(total / max_possible * 100), 2)
        return score, {"items": items, "max_possible": max_possible}

    def get_fundamental_score(self, stock_info: dict, financial_data: dict) -> dict:
        """基本面总分 = 估值×0.30 + 成长×0.40 + 健康×0.30。

        缺失子项按"可用满分"归一（不按 0 评分）；财务指标整体缺失时
        incomplete=True 提示数据缺口。
        """
        v_score, v_detail = self.score_valuation(stock_info, financial_data)
        g_score, g_detail = self.score_growth(financial_data)
        h_score, h_detail = self.score_health(financial_data)
        score = round(_clamp(v_score * WEIGHTS["valuation"] + g_score * WEIGHTS["growth"]
                             + h_score * WEIGHTS["health"]), 2)
        fin = financial_data.get("fina_indicator")
        data_complete = fin is not None and len(fin) > 0
        from services.technical import rating_of
        return {
            "score": score,
            "rating": rating_of(score),
            "incomplete": not data_complete,
            "valuation": {"score": v_score, "weight": WEIGHTS["valuation"], **v_detail},
            "growth": {"score": g_score, "weight": WEIGHTS["growth"], **g_detail},
            "health": {"score": h_score, "weight": WEIGHTS["health"], **h_detail},
        }
