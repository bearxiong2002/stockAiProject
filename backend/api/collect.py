"""K线数据采集路由 /api/collect/*"""
from __future__ import annotations

from fastapi import APIRouter, Query

from services.kline_collector import CollectTaskState, get_collector

router = APIRouter(prefix="/api/collect", tags=["collect"])

_collector = get_collector()


@router.post("/{code}/start")
async def start_collect(
    code: str,
    name: str = Query("", description="股票名称（前端传入，用于卡片显示）"),
    years: int = Query(1, ge=1, le=10, description="采集年数，默认1年"),
    freq: str = Query("daily", pattern="^(daily|1min|5min|15min|30min|60min)$"),
):
    """启动K线采集任务。已在采集中则返回现有进度。"""
    state = _collector.start(code, name, years=years, freq=freq)
    return _state_to_dict(state)


@router.get("/{code}/status")
async def collect_status(code: str):
    """查询采集任务进度。无任务返回 idle 状态。"""
    state = _collector.get_status(code)
    if state is None:
        return {"stock_code": code, "status": "idle", "progress": 0, "message": "未开始"}
    return _state_to_dict(state)


@router.get("/list")
async def list_collected(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
):
    """列出所有已采集K线数据的股票（分页）。"""
    return await _collector.list_collected(page=page, page_size=page_size)


@router.delete("/{code}")
async def delete_collect(code: str, freq: str = Query("daily")):
    """删除指定股票的已采集数据。"""
    removed = await _collector.delete_data(code, freq)
    return {"ok": True, "stock_code": code, "freq": freq, "removed": removed}


@router.post("/{code}/update")
async def update_collect(
    code: str,
    name: str = Query("", description="股票名称"),
    freq: str = Query("daily"),
):
    """增量更新：从已有数据的最新日期到今天补齐。"""
    state = _collector.start_update(code, name, freq=freq)
    return _state_to_dict(state)


@router.get("/{code}/check")
async def check_collect(code: str, freq: str = Query("15min")):
    """查询数据库中已有的分钟线数据情况。"""
    return await _collector.check_data(code, freq)


def _state_to_dict(state: CollectTaskState) -> dict:
    return {
        "stock_code": state.stock_code,
        "stock_name": state.stock_name,
        "freq": state.freq,
        "years": state.years,
        "status": state.status,
        "progress": state.progress,
        "message": state.message,
        "total_months": state.total_months,
        "fetched_months": state.fetched_months,
        "total_rows": state.total_rows,
        "error": state.error,
    }
