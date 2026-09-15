"""阶段 7.1: 自选股看板后端（design.md 4.8 / 6.4）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from models.database import WatchlistItem, get_session_factory
from models.schemas import WatchlistCreate, WatchlistSortPayload
from services.data_fetcher import get_data_fetcher, ts_code_of, code_from_ts

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _fetcher():
    return get_data_fetcher()


@router.get("")
async def list_watchlist():
    """自选列表 + 各股最新行情（价格/涨跌幅/成交量万手/换手率/PE/行业）。"""
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(WatchlistItem).order_by(WatchlistItem.sort_order,
                                           WatchlistItem.id))).scalars().all()
    fetcher = _fetcher()
    items = []
    data_meta: dict = {"source": None, "as_of": None, "is_stale": False, "warnings": []}
    for r in rows:
        code = code_from_ts(r.stock_code)
        entry: dict = {"id": r.id, "code": code, "stock_name": r.stock_name,
                       "sort_order": r.sort_order}
        try:
            info = fetcher.get_stock_info(r.stock_code)
            meta = info.pop("_data_meta", None) if isinstance(info, dict) else None
            entry.update({
                "name": info.get("name") or r.stock_name,
                "latest_price": info.get("latest_price"),
                "pct_change": info.get("pct_change"),
                # daily.vol 为手 → 万手 = 手 ÷ 1e4（契约口径校准见阶段3验收文档）
                "volume_wan": round((info.get("volume") or 0) / 1e4, 2),
                "turnover": info.get("turnover"),
                "pe": info.get("pe"),
                "industry": info.get("industry"),
                "trade_date": info.get("trade_date"),
            })
            if isinstance(meta, dict):
                data_meta["source"] = data_meta["source"] or meta.get("source")
                data_meta["as_of"] = data_meta["as_of"] or meta.get("as_of")
                data_meta["is_stale"] = data_meta["is_stale"] or bool(meta.get("is_stale"))
        except Exception as exc:
            entry["error"] = str(exc)
            data_meta["warnings"].append(f"{code} 行情获取失败")
        items.append(entry)
    return {"items": items, "data_meta": data_meta}


@router.post("")
async def add_watchlist(payload: WatchlistCreate):
    """添加自选（去重）。body: {code: "600519"}。"""
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    ts = ts_code_of(code)
    fetcher = _fetcher()
    try:
        info = fetcher.get_stock_info(ts)
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"股票代码无效或行情不可用: {exc}") from exc
    name = info.get("name") or code
    async with get_session_factory()() as session:
        exists = (await session.execute(
            select(WatchlistItem).where(WatchlistItem.stock_code == ts))).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(status_code=409, detail=f"{name} 已在自选列表")
        row = WatchlistItem(stock_code=ts, stock_name=name)
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=f"{name} 已在自选列表") from exc
        await session.refresh(row)
        return {"id": row.id, "code": code_from_ts(ts), "stock_name": name,
                "latest_price": info.get("latest_price"),
                "pct_change": info.get("pct_change"),
                "industry": info.get("industry")}


@router.delete("/{code}")
async def remove_watchlist(code: str):
    """移除自选。"""
    ts = ts_code_of(code)
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(WatchlistItem).where(WatchlistItem.stock_code == ts))
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"自选中不存在: {code}")
    return {"ok": True, "removed": result.rowcount}


@router.put("/sort")
async def sort_watchlist(payload: WatchlistSortPayload):
    """按给定代码顺序重排。body: {codes: ["600519", ...]}。"""
    codes = payload.codes
    if not codes:
        raise HTTPException(status_code=400, detail="缺少 codes")
    async with get_session_factory()() as session:
        for i, code in enumerate(codes):
            ts = ts_code_of(str(code))
            row = (await session.execute(
                select(WatchlistItem).where(WatchlistItem.stock_code == ts))).scalar_one_or_none()
            if row is not None:
                row.sort_order = i
        await session.commit()
    return {"ok": True, "sorted": len(codes)}
