"""个股数据路由 /api/stock/*（阶段3）。

- /search /list: 阶段2 契约不变；响应头补充数据来源/日期/过期状态
- /{code}/info: 个股基本信息 + data_meta（design.md §6.2）
- /{code}/kline: K线 {items, data_meta}；默认 250 交易日、period/adjust 可选，
  显式成对 start_date/end_date 优先于 days
- 分析类接口（/technical /fundamental /report）属阶段4，不在本阶段实现
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from config import settings
from models.schemas import KlineResponse, StockBrief, StockInfoResponse
from services.data_fetcher import code_from_ts, get_data_fetcher, ts_code_of
from services.fundamental import FundamentalEngine
from services.providers.normalize import iso_to_yyyymmdd
from services.report_builder import ReportBuilder
from services.scorer import ScoringEngine
from services.technical import TechnicalEngine

router = APIRouter(prefix="/api/stock", tags=["stock"])

_fetcher = get_data_fetcher()


def _data_headers(meta: dict | None) -> dict[str, str]:
    """数据质量响应头（成功与缓存路径一致）。"""
    if not meta:
        return {}
    headers = {}
    if meta.get("source"):
        headers["X-Data-Source"] = str(meta["source"])
    if meta.get("trade_date"):
        headers["X-Data-As-Of"] = str(meta["trade_date"])
    headers["X-Data-Stale"] = "1" if meta.get("is_stale") else "0"
    return headers


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if v is None or v != v:  # None / NaN
                clean[k] = None
            elif isinstance(v, pd.Timestamp):
                clean[k] = str(v.date())
            elif hasattr(v, "item"):
                clean[k] = v.item()
            else:
                clean[k] = v
        out.append(clean)
    return out


@router.get("/search")
def search_stocks(q: str = Query(..., min_length=1,
                                 description="关键词: 股票代码前缀或名称包含"),
                  response: Response = Response()):
    """股票搜索（阶段2 契约不变；响应头附数据来源/时间）。"""
    items, headers = _search_impl(q)
    response.headers.update(headers)
    return items


def _search_impl(q: str) -> tuple[list[StockBrief], dict[str, str]]:
    """搜索逻辑（便于直接调用/测试，脱离 FastAPI 注入）。"""
    keyword = q.strip()
    df = _fetcher.get_stock_list()
    meta = df.attrs.get("data_meta", {})
    if not keyword:
        return [], _data_headers(meta)
    mask = df["code"].str.startswith(keyword) | df["name"].str.contains(
        keyword, regex=False
    )
    matched = df[mask].head(20)
    return ([StockBrief(code=row.code, name=row.name, industry=row.industry,
                        market=row.market)
             for row in matched.itertuples(index=False)],
            _data_headers(meta))


@router.get("/list")
def list_stocks(response: Response = Response()):
    """全量 A 股列表（前端本地过滤用）；阶段2 契约不变。"""
    items, headers = _list_impl()
    response.headers.update(headers)
    return items


def _list_impl() -> tuple[list[StockBrief], dict[str, str]]:
    df = _fetcher.get_stock_list()
    meta = df.attrs.get("data_meta", {})
    return ([StockBrief(code=row.code, name=row.name, industry=row.industry,
                        market=row.market)
             for row in df.itertuples(index=False)],
            _data_headers(meta))


@router.get("/{code}/kline", response_model=KlineResponse)
def get_kline(
    code: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(250, ge=30, le=2500, description="默认返回最近 N 个交易日"),
    adjust: str = Query("qfq", pattern="^(qfq|hfq|)$"),
    start_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                   description="显式区间开始（优先于 days）"),
    end_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """K线数据 {items, data_meta}；显式区间优先，否则按 as_of 回溯 days。"""
    resolved_start = start_date
    if resolved_start is None:
        base_day = datetime.fromisoformat(end_date or _iso_today_like())
        resolved_start = (base_day - timedelta(days=int(days * 1.55) + 15)).strftime("%Y-%m-%d")
    df = _fetcher.get_kline(code, period=period, start_date=resolved_start,
                            end_date=end_date, adjust=adjust)
    return KlineResponse(items=_records(df), data_meta=df.attrs.get("data_meta") or {})


def _iso_today_like() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


@router.get("/{code}/info", response_model=StockInfoResponse)
def get_stock_info(code: str):
    """个股基本信息 + data_meta。"""
    info = _fetcher.get_stock_info(code)
    meta = info.pop("_data_meta", None)
    return StockInfoResponse(info=info, data_meta=meta or {})


# =====================================================================
# 阶段 4: 技术分析 / 基本面 / 综合报告
# ===================================================================

_tech_engine = TechnicalEngine()
_fund_engine = FundamentalEngine()
_scorer = ScoringEngine()


@router.get("/{code}/technical")
def get_technical(code: str, days: int = 250, period: str = "daily"):
    """技术分析结果（评分 + 子维度 + 信号 + 画图序列）。

    days 为自然日回溯基数（交易日 ≈ days×1.55）；范围校验在函数内完成，
    以便直调/测试不经过 FastAPI 注入也能工作。
    """
    if not (60 <= days <= 2500):
        raise HTTPException(status_code=400, detail="days 需在 60~2500 之间")
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="period 仅支持 daily/weekly/monthly")
    base_day = datetime.now(timezone(timedelta(hours=8)))
    start = (base_day - timedelta(days=int(days * 1.55) + 15)).strftime("%Y-%m-%d")
    df = _fetcher.get_kline(code, period=period, start_date=start, adjust="qfq")
    ind = _tech_engine.compute_all(df)
    result = _tech_engine.get_technical_score(df, ind)
    result["indicator_series"] = _tech_engine.indicator_series(df, ind)
    result["data_meta"] = df.attrs.get("data_meta") or {}
    return result


@router.get("/{code}/fundamental")
def get_fundamental(code: str):
    """基本面分析结果（估值/成长/健康度 + 评分）。"""
    ts = ts_code_of(code)
    info = _fetcher.get_stock_info(ts)
    valuation = _fetcher.get_stock_valuation(ts)
    industry = str(info.get("industry") or "")
    try:
        ind_pepb = _fetcher.get_industry_pe_pb(industry)
    except Exception as exc:
        ind_pepb = {"warning": f"行业估值基准不可用: {exc}"}
    fin = {
        "fina_indicator": _fetcher.get_financial_indicator(ts),
        "income": _fetcher.get_profit_sheet(ts),
        "balance": _fetcher.get_balance_sheet(ts),
        "cashflow": _fetcher.get_cashflow_sheet(ts),
    }
    merged = {**info, **{k: v for k, v in valuation.items() if k != "_data_meta"}}
    result = _fund_engine.get_fundamental_score(
        merged, {**fin, "industry_pe_pb": ind_pepb})
    result["data_meta"] = (valuation.get("_data_meta")
                           if isinstance(valuation, dict) else None) or {}
    return result


async def _save_report_history(report: dict) -> None:
    """报告完成写入 report_history（rating/score NOT NULL，数据不足记 0 分）。"""
    from models.database import ReportHistory, get_session_factory
    info = report.get("stock_info") or {}
    rating = report.get("rating") or {}
    score = rating.get("score")
    async with get_session_factory()() as session:
        session.add(ReportHistory(
            stock_code=str(info.get("code") or ""),
            stock_name=str(info.get("name") or ""),
            rating=str(rating.get("label") or "数据不足"),
            score=float(score) if score is not None else 0.0,
            summary=report.get("summary"),
        ))
        await session.commit()


@router.get("/{code}/report")
async def stock_report(code: str):
    """完整分析报告（SSE 流式: progress 事件 × N + report 终事件）。"""
    builder = ReportBuilder()

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def pump():
            it = iter(builder.build_report(code))
            try:
                while True:
                    ev = await asyncio.to_thread(lambda it=it: next(it, None))
                    if ev is None:
                        break
                    await queue.put(ev)
            except Exception as exc:
                await queue.put({"stage": "error", "progress": 100,
                                 "message": f"报告生成失败: {exc}"})
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                if ev.get("stage") == "report":
                    report = ev.get("report") or {}
                    await _save_report_history(report)
                    yield f"event: report\ndata: {json.dumps(report, ensure_ascii=False)}\n\n"
                else:
                    yield f"event: progress\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            # 客户端断开: 取消 pump 并等待收尾。同步 DataFetcher 步骤本身
            # 无法强制中断（asyncio.to_thread 限制），其内部 60s 请求预算兜底；
            # 这里等待 task 结束以避免 orphan 推送。
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/report/history")
async def recent_report_history(limit: int = 10):
    """全局最近报告（跨股票，SearchPanel 最近搜索用）。"""
    from models.database import ReportHistory, get_session_factory
    if not (1 <= limit <= 100):
        raise HTTPException(status_code=400, detail="limit 需在 1~100 之间")
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(ReportHistory)
            .order_by(ReportHistory.id.desc()).limit(limit))).scalars().all()
        return {"items": [
            {"id": r.id, "stock_code": r.stock_code, "stock_name": r.stock_name,
             "rating": r.rating, "score": r.score, "summary": r.summary,
             "created_at": r.created_at}
            for r in rows]}


@router.get("/{code}/report/history")
async def stock_report_history(code: str, limit: int = 20):
    """该股票历史报告列表（report_history 表，倒序）。"""
    from models.database import ReportHistory, get_session_factory
    if not (1 <= limit <= 100):
        raise HTTPException(status_code=400, detail="limit 需在 1~100 之间")
    ts = ts_code_of(code)
    stock_code = code_from_ts(ts)
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(ReportHistory)
            .where(ReportHistory.stock_code == stock_code)
            .order_by(ReportHistory.id.desc()).limit(limit))).scalars().all()
        return {"code": stock_code, "items": [
            {"id": r.id, "stock_name": r.stock_name, "rating": r.rating,
             "score": r.score, "summary": r.summary, "created_at": r.created_at}
            for r in rows]}
