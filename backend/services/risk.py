"""RiskEngine — 持仓风险评估引擎（阶段 6.2，按 design.md 4.7.2）。

输入为持仓列表（含 quantity/cost_price/latest_price/stock_code/industry）。
组合日收益率 = 各股 250 日收益率按当前市值权重逐日加权；日期对齐取交集，
停牌/缺日该股当日贡献为 None 时整行跳过（不足时如实标注，不补 0）。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

RISK_FREE_RATE = 0.02  # 年化无风险利率（夏普用）
TRADING_DAYS = 250
CST = timezone(timedelta(hours=8))


class RiskEngine:
    """组合风险指标计算。"""

    def __init__(self, fetcher):
        self._fetcher = fetcher

    # ------------------------------------------------------------------
    # 基础数据
    # ------------------------------------------------------------------

    def holdings_weights(self, holdings: list[dict]) -> list[tuple[dict, float]]:
        """持仓 → (持仓, 市值权重)；总市值为 0 时权重均分。"""
        values = [max(float(h.get("quantity", 0)) * float(h.get("latest_price") or 0), 0)
                  for h in holdings]
        total = sum(values)
        if total <= 0:
            n = len(holdings) or 1
            return [(h, 1 / n) for h in holdings]
        return [(h, v / total) for h, v in zip(holdings, values)]

    def get_portfolio_returns(self, holdings: list[dict]) -> pd.DataFrame:
        """各持仓 250 日日收益率对齐表（index=date, cols=code）。"""
        cols: dict[str, pd.Series] = {}
        for h in holdings:
            ts = h.get("stock_code")
            try:
                # 默认回溯 420 自然日 ≈285 交易日，覆盖 250 日窗口
                kline = self._fetcher.get_kline(ts, adjust="qfq")
            except Exception:
                continue
            if kline.empty:
                continue
            close = pd.to_numeric(kline["close"], errors="coerce")
            ret = close.pct_change().replace([np.inf, -np.inf], np.nan)
            cols[str(ts)] = pd.Series(ret.values, index=kline["date"].values)
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).dropna(how="any")  # 日期交集（缺一只即跳过该日）

    def _index_returns(self, dates: pd.Index) -> pd.Series:
        """沪深300 同期日收益率（对齐持仓日期；指数走 index_daily）。"""
        try:
            idx = self._fetcher.get_index_data("000300", period="daily")
        except Exception:
            return pd.Series(dtype=float)
        if idx is None or idx.empty:
            return pd.Series(dtype=float)
        close = pd.to_numeric(idx["close"], errors="coerce")
        ret = close.pct_change().replace([np.inf, -np.inf], np.nan)
        s = pd.Series(ret.values, index=idx["date"].values)
        return s.reindex(dates)

    # ------------------------------------------------------------------
    # 风险指标（design 4.7.2）
    # ------------------------------------------------------------------

    def calc_var(self, returns: np.ndarray, confidence: float = 0.95,
                 total_value: float = 0.0) -> dict:
        """历史模拟法 VaR: 分位取反 → 单日最大可能亏损。"""
        r = returns[~np.isnan(returns)]
        if len(r) < 30:
            return {"pct": None, "amount": None, "confidence": confidence,
                    "note": f"有效样本不足（{len(r)}<30）"}
        q = float(np.percentile(r, (1 - confidence) * 100))
        pct = round(-q * 100, 4)
        return {"pct": pct, "amount": round(pct / 100 * total_value, 2) if total_value else None,
                "confidence": confidence, "note": None}

    def calc_max_drawdown(self, nav: pd.Series) -> dict:
        """净值曲线 → 最大回撤幅度 + 起止时间 + 当前回撤。"""
        if nav is None or len(nav) < 10:
            return {"max": None, "start": None, "end": None, "current": None,
                    "note": "净值样本不足"}
        peak = nav.cummax()
        dd = 1 - nav / peak
        i_max = dd.idxmax()                      # 回撤谷值（index 标签）
        peak_series = nav.loc[:i_max].cummax()   # 谷值前的历史净值峰值
        i_start = peak_series.loc[peak_series
                                  == peak_series.iloc[-1]].index[0]
        current = float(dd.iloc[-1])
        return {
            "max": round(float(dd.max()) * 100, 2),
            "start": str(i_start), "end": str(i_max),
            "current": round(current * 100, 2), "note": None,
        }

    def calc_volatility(self, returns: np.ndarray) -> float | None:
        """日收益标准差 × √250 → 年化波动率（%）。"""
        r = returns[~np.isnan(returns)]
        if len(r) < 30:
            return None
        return round(float(np.std(r, ddof=1)) * math.sqrt(TRADING_DAYS) * 100, 2)

    def calc_beta(self, port: np.ndarray, index: np.ndarray) -> float | None:
        """组合相对基准的 Beta = cov/var。"""
        mask = ~(np.isnan(port) | np.isnan(index))
        p, b = port[mask], index[mask]
        if len(p) < 30:
            return None
        var_b = float(np.var(b, ddof=1))
        if var_b <= 0:
            return None
        return round(float(np.cov(p, b, ddof=1)[0, 1]) / var_b, 4)

    def calc_sharpe(self, returns: np.ndarray,
                    risk_free_rate: float = RISK_FREE_RATE) -> float | None:
        """年化收益-无风险利率 / 年化波动率。"""
        r = returns[~np.isnan(returns)]
        if len(r) < 30:
            return None
        ann_return = float(np.mean(r)) * TRADING_DAYS
        vol = float(np.std(r, ddof=1)) * math.sqrt(TRADING_DAYS)
        if vol <= 0:
            return None
        return round((ann_return - risk_free_rate) / vol, 4)

    def calc_concentration(self, holdings: list[dict]) -> dict:
        """HHI + 前 3 大占比 + 评级（design: >0.25 高 / 0.15-0.25 中 / <0.15 分散）。"""
        pairs = self.holdings_weights(holdings)
        weights = [w for _, w in pairs]
        hhi = round(sum(w * w for w in weights), 4)
        top3 = round(sum(sorted(weights, reverse=True)[:3]) * 100, 2)
        if hhi > 0.25:
            level = "高集中"
        elif hhi >= 0.15:
            level = "中等"
        else:
            level = "分散"
        return {"hhi": hhi, "top3_pct": top3, "level": level,
                "count": len(holdings)}

    def calc_sector_exposure(self, holdings: list[dict]) -> dict:
        """行业分布 {industry: 占比%}；单一行业 >40% 警告。"""
        pairs = self.holdings_weights(holdings)
        sectors: dict[str, float] = {}
        industry_of: dict[str, str] = {}
        for h, w in pairs:
            ind = str(h.get("industry") or "未知")
            sectors[ind] = sectors.get(ind, 0) + w
            industry_of[str(h.get("stock_code"))] = ind
        out = [{"industry": k, "weight_pct": round(v * 100, 2),
                "stock_codes": [code for code, ind in industry_of.items() if ind == k]}
               for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]
        warnings = [f"单一行业 {o['industry']} 占比 {o['weight_pct']:.1f}% 超过 40%"
                    for o in out if o["weight_pct"] > 40]
        return {"sectors": out, "count": len(out), "warnings": warnings}

    def calc_correlation_matrix(self, returns_df: pd.DataFrame) -> dict:
        """持仓收益率相关系数矩阵（对角线=1）。"""
        if returns_df is None or returns_df.empty or returns_df.shape[1] < 1:
            return {"codes": [], "matrix": [], "high_pairs": []}
        corr = returns_df.corr(min_periods=30)
        codes = list(corr.columns)
        matrix = [[round(float(corr.loc[a, b]), 4) if not pd.isna(corr.loc[a, b]) else None
                   for b in codes] for a in codes]
        high = []
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                v = matrix[i][j]
                if v is not None and abs(v) > 0.7:
                    high.append({"pair": [codes[i], codes[j]], "corr": v})
        return {"codes": codes, "matrix": matrix, "high_pairs": high}

    def calc_portfolio_curve(self, holdings: list[dict],
                             returns_df: pd.DataFrame) -> dict:
        """组合净值曲线 vs 沪深300（起点归一 1.0）。"""
        if returns_df is None or returns_df.empty:
            return {"dates": [], "portfolio": [], "benchmark": [],
                    "note": "收益率数据不足"}
        pairs = self.holdings_weights(holdings)
        w = dict(zip([str(h.get("stock_code")) for h, _ in pairs],
                     [w for _, w in pairs]))
        port_ret = pd.Series(0.0, index=returns_df.index, dtype=float)
        for code in returns_df.columns:
            port_ret = port_ret + w.get(code, 0) * returns_df[code].fillna(0)
        nav_port = (1 + port_ret).cumprod()
        idx = self._index_returns(returns_df.index)
        nav_bench = (1 + idx.fillna(0)).cumprod() if len(idx) else None
        dates = [str(d) for d in returns_df.index]
        return {
            "dates": dates,
            "portfolio": [round(float(v), 4) for v in nav_port],
            "benchmark": [round(float(v), 4) for v in nav_bench] if nav_bench is not None else [],
            "note": None,
        }

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def get_risk_assessment(self, holdings: list[dict]) -> dict:
        """全部风险指标 + 风险等级（高/中/低）。"""
        empty = {"note": "无持仓或数据不足，无法评估风险"}
        if not holdings:
            return {**empty, "incomplete": True}
        weights = self.holdings_weights(holdings)
        total_value = sum(float(h.get("quantity", 0)) * float(h.get("latest_price") or 0)
                          for h in holdings)
        returns_df = self.get_portfolio_returns(holdings)
        if returns_df.empty or len(returns_df) < 60:
            return {**empty, "incomplete": True,
                    "detail": f"有效共同交易日仅 {len(returns_df) if not returns_df.empty else 0} 天"}
        pairs = dict(zip([str(h.get("stock_code")) for h, _ in weights],
                         [w for _, w in weights]))
        port_ret = pd.Series(0.0, index=returns_df.index)
        for code in returns_df.columns:
            port_ret = port_ret + pairs.get(code, 0) * returns_df[code].fillna(0)
        port_arr = port_ret.values
        idx_ret = self._index_returns(returns_df.index)
        index_arr = idx_ret.reindex(returns_df.index).values
        nav_port = (1 + port_ret).cumprod()
        var95 = self.calc_var(port_arr, 0.95, total_value)
        var99 = self.calc_var(port_arr, 0.99, total_value)
        vol = self.calc_volatility(port_arr)
        vol_idx = self.calc_volatility(index_arr)
        beta = self.calc_beta(port_arr, index_arr)
        sharpe = self.calc_sharpe(port_arr)
        conc = self.calc_concentration(holdings)
        sector = self.calc_sector_exposure(holdings)
        corr = self.calc_correlation_matrix(returns_df)
        curve = self.calc_portfolio_curve(holdings, returns_df)
        dd = self.calc_max_drawdown(nav_port)
        # 风险等级: 各指标按阈值计 1 分，≥3 高 / 1-2 中 / 0 低
        score = sum([
            (var95.get("pct") or 0) > 3.0,
            (dd.get("max") or 0) > 25,
            (vol or 0) > 35,
            (beta is not None and beta > 1.2),
            conc["level"] == "高集中",
        ])
        level = "高风险" if score >= 3 else ("中风险" if score >= 1 else "低风险")
        warnings: list[str] = []
        warnings.extend(sector["warnings"])
        for hp in corr["high_pairs"]:
            warnings.append(f"{hp['pair'][0]} 与 {hp['pair'][1]} 相关性 {hp['corr']:.2f} 超过 0.7")
        return {
            "total_market_value": round(total_value, 2),
            "sample_days": int(len(returns_df)),
            "var": {"95": var95, "99": var99},
            "max_drawdown": dd,
            "volatility": {"portfolio": vol, "index": vol_idx},
            "beta": beta,
            "sharpe": sharpe,
            "concentration": conc,
            "sector_exposure": sector,
            "correlation": corr,
            "portfolio_curve": curve,
            "risk_level": level,
            "warnings": warnings,
            "incomplete": False,
        }
