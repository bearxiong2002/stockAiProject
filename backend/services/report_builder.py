"""ReportBuilder — 报告组装器（阶段 4.4；阶段 8 接入 AI 分析）。

build_report(code) 为同步生成器，逐阶段 yield 进度事件，最后 yield 完整报告
（design.md 6.2 JSON 结构）。API 层以队列桥接转换为 SSE 流并在完成时写
report_history。

降级原则:
- 逐段透传 data_meta（来源/数据日期/缺失/stale 警告）；
- 核心数据不足（K 线 < 60 行）时不产出完整评级（rating.score=null）；
- 可选指标缺失不按 0 评分（基本面/技术面引擎内部按可用满分归一）；
- AI（阶段 8）: 有 Key 且调用成功 → 权重 35/35/30；未配置/失败/无新闻 →
  回退 50/50 并在报告中标注"AI 分析不可用"，不阻塞报告产出（design §4.5.1、§11.2）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pandas as pd

from services.ai_analyzer import AIAnalyzer
from services.data_fetcher import get_data_fetcher, ts_code_of, code_from_ts
from services.fundamental import FundamentalEngine
from services.scorer import DISCLAIMER, ScoringEngine
from services.technical import TechnicalEngine

FUND_FLOW_CHART_ROWS = 20
AI_UNAVAILABLE_NOTE = "AI 分析不可用（未配置 LLM API Key），综合评分按技术面/基本面 50/50 权重"


class ReportBuilder:
    """组装个股完整分析报告（技术 + 基本面 + 综合评级）。"""

    def __init__(self):
        self._fetcher = get_data_fetcher()
        self._tech = TechnicalEngine()
        self._fund = FundamentalEngine()
        self._scorer = ScoringEngine()

    # ------------------------------------------------------------------
    # 进度事件生成器
    # ------------------------------------------------------------------

    def build_report(self, code: str) -> Iterator[dict]:
        """生成完整报告。事件结构:
        {"stage": str, "progress": int, "message": str}
        最终事件 {"stage": "report", "progress": 100, "report": dict}
        """
        ts = ts_code_of(code)

        def emit(stage: str, progress: int, message: str) -> dict:
            return {"stage": stage, "progress": progress, "message": message}

        yield emit("fetching_data", 10, "正在获取行情与基本面数据...")

        # -- 数据获取（逐段透传 data_meta/warnings）------------------------
        meta: dict[str, Any] = {"source": None, "as_of": None, "is_stale": False,
                                "warnings": [], "coverage": {}}
        warnings: list[str] = []
        try:
            # 默认回溯 420 自然日 ≈285 交易日，满足 MA250/251 价格点需求
            kline = self._fetcher.get_kline(ts, adjust="qfq")
            k_meta = kline.attrs.get("data_meta", {})
        except Exception as exc:  # 核心数据失败 → 报告不可产出
            yield {"stage": "report", "progress": 100,
                   "report": {"error": f"行情数据获取失败: {exc}",
                              "stock_info": {"code": code}}}
            return
        info = self._fetcher.get_stock_info(ts)
        info_meta = info.get("_data_meta", {}) if isinstance(info, dict) else {}
        valuation = self._fetcher.get_stock_valuation(ts)
        industry = str(info.get("industry") or "")
        try:
            ind_pepb = self._fetcher.get_industry_pe_pb(industry)
        except Exception as exc:
            ind_pepb = {"warning": f"行业估值基准不可用: {exc}"}
            warnings.append(f"行业估值基准不可用: {exc}")
        fin: dict[str, pd.DataFrame] = {}
        try:
            fin["fina_indicator"] = self._fetcher.get_financial_indicator(ts)
            fin["income"] = self._fetcher.get_profit_sheet(ts)
            fin["balance"] = self._fetcher.get_balance_sheet(ts)
            fin["cashflow"] = self._fetcher.get_cashflow_sheet(ts)
        except Exception as exc:
            warnings.append(f"财务数据获取失败: {exc}")
        try:
            flow = self._fetcher.get_fund_flow(ts)
        except Exception as exc:
            flow = pd.DataFrame()
            warnings.append(f"资金流数据获取失败: {exc}")
        try:
            news = self._fetcher.get_stock_news(ts)
        except Exception as exc:
            news = pd.DataFrame()
            warnings.append(f"新闻数据获取失败: {exc}")

        # 合并 meta
        for m in (k_meta, info_meta):
            if not m:
                continue
            meta["source"] = meta["source"] or m.get("source")
            meta["as_of"] = meta["as_of"] or m.get("as_of") or m.get("trade_date")
            meta["is_stale"] = meta["is_stale"] or bool(m.get("is_stale"))
        meta["warnings"] = list(dict.fromkeys(
            [w for m in (k_meta, info_meta) for w in (m.get("warnings") or [])]
            + warnings))
        fin_ind = fin.get("fina_indicator")
        meta["coverage"] = {"kline_rows": int(len(kline)),
                            "fin_rows": int(len(fin_ind)) if fin_ind is not None else 0,
                            "fund_flow_rows": int(len(flow)),
                            "news_rows": int(len(news))}

        yield emit("technical_analysis", 30, "正在计算技术指标...")

        tech_ind = self._tech.compute_all(kline)
        technical = self._tech.get_technical_score(kline, tech_ind)

        yield emit("fundamental_analysis", 50, "正在分析基本面...")

        financial_data = {**fin, "industry_pe_pb": ind_pepb}
        merged_info = {**info, **{k: v for k, v in valuation.items()
                                  if k not in ("_data_meta",)}}
        fundamental = self._fund.get_fundamental_score(merged_info, financial_data)

        # -- AI 分析（阶段 8）: 情绪分析 → 综合点评；失败逐项降级 -----------
        yield emit("ai_analysis", 62, "正在检查 AI 分析配置...")

        sentiment_block = self._empty_sentiment_block(news)
        ai_report: dict | None = None
        sentiment_score: float | None = None
        analyzer = AIAnalyzer()
        ai_meta: dict[str, Any] = {
            "available": analyzer.available,
            "provider": analyzer.provider if analyzer.available else None,
            "model": analyzer.model if analyzer.available else None,
            "errors": [],
        }
        if not analyzer.available:
            sentiment_block["note"] = AI_UNAVAILABLE_NOTE
            ai_meta["note"] = AI_UNAVAILABLE_NOTE
            yield emit("ai_analysis", 70, AI_UNAVAILABLE_NOTE)
        else:
            if sentiment_block["news_list"]:
                yield emit("ai_analysis", 66, "AI 正在分析新闻情绪...")
                sentiment = analyzer.analyze_news_sentiment(
                    sentiment_block["news_list"],
                    stock_name=str(info.get("name") or ""),
                    code=code_from_ts(ts))
                if sentiment:
                    sentiment_score = sentiment["sentiment_score"]
                    sentiment_block.update({
                        "overall": sentiment["overall_sentiment"],
                        "score": sentiment["sentiment_score"],
                        "key_events": sentiment["key_events"],
                        "summary": sentiment["summary"],
                        "distribution": sentiment["distribution"],
                        "note": f"AI 情绪分析（{analyzer.provider} / {analyzer.model}）",
                    })
                else:
                    message = (analyzer.last_error or {}).get("message") or "未知错误"
                    ai_meta["errors"].append(f"新闻情绪分析失败: {message}")
                    sentiment_block["note"] = f"AI 新闻情绪分析失败，已降级为纯算法评分（{message}）"
            else:
                sentiment_block["note"] = "窗口内无可靠关联新闻，新闻情绪不计入评分"

            rating_preview = self._scorer.calculate_rating(
                technical.get("score"), fundamental.get("score"), sentiment_score)
            yield emit("ai_analysis", 74, "AI 正在生成综合点评...")
            ai_report = analyzer.generate_analysis_report({
                "stock_info": {
                    "code": code_from_ts(ts), "name": info.get("name"),
                    "industry": info.get("industry"),
                    "latest_price": info.get("latest_price"),
                    "pct_change": info.get("pct_change"),
                    "market_cap": info.get("market_cap"),
                    "trade_date": info.get("trade_date"),
                },
                "rating": rating_preview,
                "technical_result": technical,
                "fundamental_result": fundamental,
                "fund_flow": self._fund_flow_block(flow),
                "news_sentiment": {"overall": sentiment_block["overall"],
                                   "score": sentiment_block["score"],
                                   "summary": sentiment_block.get("summary"),
                                   "key_events": sentiment_block["key_events"]},
                "kline_summary": self._kline_summary(kline, tech_ind),
                "warnings": meta.get("warnings") or [],
            })
            if ai_report is None:
                message = (analyzer.last_error or {}).get("message") or "未知错误"
                ai_meta["errors"].append(f"综合点评生成失败: {message}")
            else:
                ai_meta["generated"] = True
            ai_meta["weights"] = rating_preview.get("weights")

        if ai_meta["errors"]:
            meta["warnings"] = list(dict.fromkeys(
                list(meta.get("warnings") or []) + ai_meta["errors"]))

        yield emit("building_report", 90, "正在生成报告...")

        rating = self._scorer.calculate_rating(technical.get("score"),
                                               fundamental.get("score"),
                                               sentiment_score)
        report = self._assemble(ts, info, technical, fundamental, rating,
                                flow, news, kline, meta, tech_ind,
                                sentiment_block=sentiment_block,
                                ai_report=ai_report, ai_meta=ai_meta)
        report["disclaimer"] = DISCLAIMER
        yield {"stage": "report", "progress": 100, "report": report}

    # ------------------------------------------------------------------
    # 报告组装
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_sentiment_block(news: pd.DataFrame | None) -> dict:
        news_rows = (news.head(10).to_dict(orient="records")
                     if news is not None and len(news) else [])
        return {"overall": None, "score": None, "key_events": [], "summary": None,
                "distribution": None, "news_list": news_rows, "note": ""}

    @staticmethod
    def _kline_summary(kline: pd.DataFrame, tech_ind: pd.DataFrame | None) -> dict:
        """给 AI 的少量价格位置摘要（不传全量 K 线，控制 token）。"""
        out: dict[str, Any] = {}
        try:
            close = pd.to_numeric(kline["close"], errors="coerce").dropna()
            if close.empty:
                return out
            last = float(close.iloc[-1])
            out["close"] = last
            if tech_ind is not None and len(tech_ind):
                for col in ("ma_5", "ma_20", "ma_60"):
                    if col in tech_ind.columns:
                        value = tech_ind[col].iloc[-1]
                        out[col] = None if pd.isna(value) else round(float(value), 2)
            for days, key in ((20, "pct_20d"), (60, "pct_60d")):
                if len(close) > days:
                    base = float(close.iloc[-(days + 1)])
                    if base:
                        out[key] = round((last / base - 1) * 100, 2)
        except Exception:  # 摘要非核心，失败留空
            pass
        return out

    def _fund_flow_block(self, flow: pd.DataFrame) -> dict:
        if flow is None or flow.empty:
            return {"main_net_inflow_5d": None, "trend": "unknown",
                    "chart_data": [], "note": "资金流数据不可用"}
        recent = flow.tail(5)
        sum5 = float(recent["main_net_inflow"].sum())
        pct = pd.to_numeric(flow["main_net_inflow_pct"], errors="coerce")
        pct_5 = pct.tail(5)
        # "5日均值"按可用日计算——有效值 ≥3 天才输出，否则置 None 避免误导
        pct_5d = round(float(pct_5.mean()), 4) if int(pct_5.notna().sum()) >= 3 else None
        chart = flow.tail(FUND_FLOW_CHART_ROWS)[
            ["date", "main_net_inflow", "main_net_inflow_pct",
             "super_large_net", "large_net"]].to_dict(orient="records")
        return {
            "main_net_inflow_5d": round(sum5, 4),
            "trend": "inflow" if sum5 > 0 else "outflow",
            "main_net_inflow_pct_5d": pct_5d,
            "chart_data": chart,
        }

    def _rule_summary(self, rating: dict, technical: dict,
                      fundamental: dict) -> str:
        if rating.get("score") is None:
            return "核心数据不足，暂不产出完整评级。"
        t = technical.get("rating") or "无数据"
        f = fundamental.get("rating") or "无数据"
        return (f"综合评级 {rating['level']} {rating['label']}"
                f"（{rating['score']:+.1f} 分）：技术面{t}，基本面{f}。"
                f"{rating.get('action') or ''}")

    def _assemble(self, ts: str, info: dict, technical: dict, fundamental: dict,
                  rating: dict, flow: pd.DataFrame, news: pd.DataFrame,
                  kline: pd.DataFrame, meta: dict,
                  tech_ind: pd.DataFrame | None = None,
                  sentiment_block: dict | None = None,
                  ai_report: dict | None = None,
                  ai_meta: dict | None = None) -> dict:
        kline_rows = [
            {k: (None if (v is None or (isinstance(v, float) and pd.isna(v))) else
                 (round(float(v), 4) if isinstance(v, (int, float)) else v))
             for k, v in row.items()}
            for row in kline[["date", "open", "close", "high", "low", "volume",
                              "amount", "amplitude", "pct_change", "change",
                              "turnover"]].to_dict(orient="records")
        ]
        return {
            "stock_info": {
                "code": code_from_ts(ts),
                "name": info.get("name"),
                "industry": info.get("industry"),
                "market": info.get("market"),
                "market_cap": info.get("market_cap"),
                "latest_price": info.get("latest_price"),
                "pct_change": info.get("pct_change"),
                "trade_date": info.get("trade_date"),
            },
            "rating": rating,
            "technical": technical,
            "fundamental": fundamental,
            "fund_flow": self._fund_flow_block(flow),
            "news_sentiment": sentiment_block or self._empty_sentiment_block(news),
            "ai_report": ai_report,
            "ai_meta": ai_meta or {"available": False,
                                   "note": AI_UNAVAILABLE_NOTE, "errors": []},
            "kline_data": kline_rows,
            "indicator_data": self._tech.indicator_series(kline, tech_ind),
            "data_meta": meta,
            "generated_at": datetime.now(timezone(timedelta(hours=8)))
            .strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "summary": self._rule_summary(rating, technical, fundamental),
        }
