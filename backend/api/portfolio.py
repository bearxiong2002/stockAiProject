"""阶段 6.1: 持仓 CRUD + 实时计算 + 6.2: 风险评估路由（design.md 6.3）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select

from config import settings
from models.database import Holding, get_session_factory
from models.schemas import (HoldingCreate, HoldingUpdate, HoldingView,
                            HoldingsResponse, PortfolioSummary)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_CST = timezone(timedelta(hours=8))


def _now_cst() -> datetime:
    return datetime.now(_CST)


def _hold_days(buy_date: str | None) -> int | None:
    if not buy_date:
        return None
    try:
        d = datetime.fromisoformat(buy_date[:10]).date()
    except ValueError:
        return None
    return max((_now_cst().date() - d).days, 0)


def _fetcher():
    from services.data_fetcher import get_data_fetcher
    return get_data_fetcher()


def _risk_engine():
    from services.risk import RiskEngine
    return RiskEngine(_fetcher())


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

@router.get("/holdings")
async def list_holdings() -> HoldingsResponse:
    """全部持仓 + 实时计算字段（现价/市值/盈亏/占比/持有天数）+ 汇总。"""
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(Holding).order_by(Holding.id))).scalars().all()
    items = [
        {"id": r.id, "stock_code": r.stock_code, "stock_name": r.stock_name,
         "quantity": r.quantity, "cost_price": r.cost_price,
         "buy_date": r.buy_date, "notes": r.notes}
        for r in rows
    ]
    data_meta: dict = {"source": None, "as_of": None, "is_stale": False, "warnings": []}
    fetcher = _fetcher()
    # 现价与行业: get_stock_info（有缓存）；失败保留原值并记录 warning
    for item in items:
        item.setdefault("industry", None)
        try:
            info = fetcher.get_stock_info(item["stock_code"])
            meta = info.pop("_data_meta", None) if isinstance(info, dict) else None
            item["latest_price"] = info.get("latest_price")
            item["industry"] = info.get("industry")
            if info.get("name"):
                item["stock_name"] = info["name"]
            item["trade_date"] = info.get("trade_date")
            if isinstance(meta, dict):
                data_meta["source"] = data_meta["source"] or meta.get("source")
                data_meta["as_of"] = data_meta["as_of"] or meta.get("as_of")
                data_meta["is_stale"] = data_meta["is_stale"] or bool(meta.get("is_stale"))
        except Exception as exc:
            data_meta["warnings"].append(f"{item['stock_code']} 行情获取失败: {exc}")
    total_value = sum((it["latest_price"] or 0) * it["quantity"] for it in items)
    total_cost = sum(it["cost_price"] * it["quantity"] for it in items)
    for it in items:
        price = it["latest_price"]
        it["market_value"] = round(price * it["quantity"], 2) if price is not None else None
        it["profit"] = round((price - it["cost_price"]) * it["quantity"], 2) \
            if price is not None else None
        it["profit_pct"] = round((price / it["cost_price"] - 1) * 100, 2) \
            if price is not None and it["cost_price"] > 0 else None
        it["weight"] = round(price * it["quantity"] / total_value * 100, 2) \
            if price is not None and total_value > 0 else None
        it["hold_days"] = _hold_days(it["buy_date"])
    return HoldingsResponse(
        holdings=[HoldingView(**it) for it in items],
        summary=PortfolioSummary(
            total_market_value=round(total_value, 2),
            total_cost=round(total_cost, 2),
            total_profit=round(total_value - total_cost, 2),
            total_profit_pct=round((total_value / total_cost - 1) * 100, 2)
            if total_cost > 0 else 0.0,
            count=len(items),
        ),
        data_meta=data_meta,
    )


@router.post("/holdings")
async def add_holding(payload: HoldingCreate) -> HoldingView:
    """添加持仓（校验代码有效性：可从数据源获取行情）。"""
    fetcher = _fetcher()
    try:
        info = fetcher.get_stock_info(payload.stock_code)
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"股票代码无效或行情不可用: {exc}") from exc
    name = payload.stock_name or info.get("name") or payload.stock_code
    async with get_session_factory()() as session:
        row = Holding(
            stock_code=str(info.get("code") or payload.stock_code),
            stock_name=name,
            quantity=payload.quantity,
            cost_price=payload.cost_price,
            buy_date=payload.buy_date,
            notes=payload.notes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        latest = info.get("latest_price")
        return HoldingView(
            id=row.id, stock_code=row.stock_code, stock_name=row.stock_name,
            quantity=row.quantity, cost_price=row.cost_price,
            buy_date=row.buy_date, notes=row.notes,
            latest_price=latest, industry=info.get("industry"),
            market_value=round(latest * row.quantity, 2) if latest is not None else None,
            profit=round((latest - row.cost_price) * row.quantity, 2)
            if latest is not None else None,
            profit_pct=round((latest / row.cost_price - 1) * 100, 2)
            if latest is not None and row.cost_price > 0 else None,
            hold_days=_hold_days(row.buy_date),
            trade_date=info.get("trade_date"),
        )


@router.put("/holdings/{holding_id}")
async def update_holding(holding_id: int, payload: HoldingUpdate) -> HoldingView:
    """修改持仓（数量/成本价/买入日期/备注）。"""
    async with get_session_factory()() as session:
        row = (await session.execute(
            select(Holding).where(Holding.id == holding_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"持仓不存在: {holding_id}")
        if payload.quantity is not None:
            row.quantity = payload.quantity
        if payload.cost_price is not None:
            row.cost_price = payload.cost_price
        if payload.buy_date is not None:
            row.buy_date = payload.buy_date
        if payload.notes is not None:
            row.notes = payload.notes
        await session.commit()
        latest: float | None = None
        industry: str | None = None
        try:
            info = _fetcher().get_stock_info(row.stock_code)
            latest = info.get("latest_price")
            industry = info.get("industry")
        except Exception:
            pass
        return HoldingView(
            id=row.id, stock_code=row.stock_code, stock_name=row.stock_name,
            quantity=row.quantity, cost_price=row.cost_price,
            buy_date=row.buy_date, notes=row.notes,
            latest_price=latest, industry=industry,
            market_value=round(latest * row.quantity, 2) if latest is not None else None,
            profit=round((latest - row.cost_price) * row.quantity, 2)
            if latest is not None else None,
            profit_pct=round((latest / row.cost_price - 1) * 100, 2)
            if latest is not None and row.cost_price > 0 else None,
            hold_days=_hold_days(row.buy_date),
        )


@router.delete("/holdings/{holding_id}")
async def remove_holding(holding_id: int):
    """删除持仓。"""
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(Holding).where(Holding.id == holding_id))
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"持仓不存在: {holding_id}")
    return {"ok": True, "removed": result.rowcount}


# ------------------------------------------------------------------
# 风险
# ------------------------------------------------------------------

async def _load_holdings_dicts() -> list[dict]:
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(Holding).order_by(Holding.id))).scalars().all()
    fetcher = _fetcher()
    items = []
    for r in rows:
        industry = None
        latest = None
        try:
            info = fetcher.get_stock_info(r.stock_code)
            latest = info.get("latest_price")
            industry = info.get("industry")
        except Exception:
            pass
        items.append({"stock_code": r.stock_code, "stock_name": r.stock_name,
                      "quantity": r.quantity, "cost_price": r.cost_price,
                      "latest_price": latest, "industry": industry,
                      "buy_date": r.buy_date})
    return items


@router.get("/risk")
async def portfolio_risk():
    """风险评估: VaR/最大回撤/波动率/Beta/夏普/集中度/行业/相关性/净值曲线。"""
    items = await _load_holdings_dicts()
    if not items:
        return {"incomplete": True, "note": "无持仓，请先添加持仓", "risk_level": None}
    return _risk_engine().get_risk_assessment(items)


@router.get("/risk/correlation")
async def portfolio_correlation():
    """相关性矩阵（独立端点，热力图专用）。"""
    items = await _load_holdings_dicts()
    engine = _risk_engine()
    returns_df = engine.get_portfolio_returns(items)
    return engine.calc_correlation_matrix(returns_df)


# AI 诊断结果短缓存: key = 持仓签名，默认 10 分钟（LLM 调用有成本）
_AI_ADVICE_TTL = 600
_ai_advice_cache: dict = {"key": None, "at": 0.0, "payload": None}


def _holdings_signature(items: list[dict]) -> str:
    return "|".join(f"{it.get('stock_code')}:{it.get('quantity')}:{it.get('cost_price')}"
                    for it in items)


@router.get("/risk/ai-advice")
async def portfolio_ai_advice(force: bool = False):
    """AI 持仓诊断建议（design.md §6.3）。

    - 未持仓 / 未配置 LLM / 调用失败 → available=false + 明确 note（前端降级展示）
    - 结果按持仓签名缓存 10 分钟；force=true 强制重新生成
    """
    import time
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    from services.ai_analyzer import AIAnalyzer

    items = await _load_holdings_dicts()
    if not items:
        return {"available": False, "advice": None, "note": "无持仓，请先添加持仓"}

    analyzer = AIAnalyzer()
    if not analyzer.available:
        return {"available": False, "advice": None, "llm_configured": False,
                "note": "AI 分析不可用（未配置 LLM API Key），请在设置页配置"}

    signature = _holdings_signature(items)
    now = time.monotonic()
    if (not force and _ai_advice_cache["payload"] is not None
            and _ai_advice_cache["key"] == signature
            and now - _ai_advice_cache["at"] < _AI_ADVICE_TTL):
        return {**_ai_advice_cache["payload"], "cached": True}

    risk = _risk_engine().get_risk_assessment(items)
    advice = analyzer.generate_portfolio_advice({
        "holdings": items,
        "risk_metrics": risk,
        "sector_exposure": risk.get("sector_exposure") if isinstance(risk, dict) else None,
    })
    if advice is None:
        error = (analyzer.last_error or {}).get("message") or "未知错误"
        return {"available": False, "advice": None, "llm_configured": True,
                "note": f"AI 调用失败，已降级（{error}）",
                "error": analyzer.last_error}
    payload = {
        "available": True,
        "advice": advice,
        "provider": analyzer.provider,
        "model": analyzer.model,
        "risk_level": risk.get("risk_level") if isinstance(risk, dict) else None,
        "generated_at": datetime.now(_CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "note": None,
    }
    _ai_advice_cache.update({"key": signature, "at": now, "payload": payload})
    return payload
