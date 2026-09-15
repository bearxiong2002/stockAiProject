"""阶段 7.3: 大盘概览数据（design.md 4.9 / 6.5）。

- indices: 4 指数最新点位/涨跌幅/成交额 + 近 30 日迷你序列
- sectors: 申万一级 31 行业当日涨跌幅 + 成交额（热力图 TreeMap）
- fund-flow: 近 10 日大盘主力净流入（moneyflow_mkt_dc）
- statistics: 全市场涨跌/平盘 + 涨跌停家数（stk_limit 价格比较，非 10% 硬编码）
"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException

from services.data_fetcher import get_data_fetcher, ts_code_of
from services.providers.normalize import yyyymmdd_to_iso

router = APIRouter(prefix="/api/market", tags=["market"])

INDEX_CODES = [("000001", "上证指数"), ("399001", "深证成指"),
               ("399006", "创业板指"), ("000688", "科创50")]


def _fetcher():
    return get_data_fetcher()


@router.get("/indices")
def indices():
    """主要指数 + 近 30 日迷你 K 线。"""
    out = []
    for code, name in INDEX_CODES:
        try:
            df = _fetcher().get_index_data(code, period="daily")
        except Exception as exc:
            out.append({"code": code, "name": name, "error": str(exc),
                        "sparkline": [], "index_kline": None})
            continue
        if df is None or df.empty:
            out.append({"code": code, "name": name, "index_kline": None,
                        "sparkline": [], "error": "无数据"})
            continue
        df = df.sort_values("date").reset_index(drop=True)
        tail = df.tail(30)
        last, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else None
        pct = None
        if prev is not None and prev["close"]:
            pct = round((last["close"] / prev["close"] - 1) * 100, 2)
        out.append({
            "code": code, "name": name,
            "close": round(float(last["close"]), 2),
            "pct_change": pct,
            "amount_yi": round(float(last["amount"]) / 1e8, 1),
            "trade_date": str(last["date"]),
            # 迷你面积图序列（近 30 日收盘）
            "sparkline": [round(float(v), 2) for v in tail["close"]],
            "index_kline": None,
        })
    return {"items": out}


@router.get("/sectors")
def sectors():
    """行业板块涨跌 + 成交额（申万一级，热力图用）。"""
    fetcher = _fetcher()
    boards = fetcher.get_industry_board_list()
    if boards is None or boards.empty:
        return {"items": [], "note": "行业板块数据暂不可用"}
    as_of = boards.attrs.get("data_meta", {}).get("trade_date") or None
    # 成交额: 当日 sw_daily（亿元）——与板块列表同一份缓存（_sw_latest_by_code）
    amounts: dict[str, float] = {}
    try:
        sw = fetcher._sw_latest_by_code(str(boards.attrs.get("data_meta", {}).get("trade_date")
                                            or _fetcher()._as_of()))
        if sw:
            for ts_code, row in sw.items():
                name = str(row.get("name") or ts_code)
                amt = row.get("amount")
                if amt is not None:
                    amounts[name] = round(float(amt), 1)
    except Exception:
        amounts = {}
    items = []
    for r in boards.to_dict(orient="records"):
        name = str(r.get("name"))
        items.append({
            "name": name,
            "code": str(r.get("code")),
            "pct_change": r.get("pct_change"),
            "turnover": r.get("turnover"),
            "amount_yi": amounts.get(name),
            "leading_stock": r.get("leading_stock"),
            "leading_pct": r.get("leading_pct"),
        })
    return {"items": items, "count": len(items)}


@router.get("/fund-flow")
def fund_flow(days: int = 10):
    """近 N 日大盘资金流向（moneyflow_mkt_dc → 亿元）。"""
    if not (1 <= days <= 30):
        raise HTTPException(status_code=400, detail="days 需在 1~30 之间")
    df = _fetcher().get_market_fund_flow()
    if df is None or df.empty:
        return {"items": [], "note": "大盘资金流数据暂不可用"}
    df = df.sort_values("date").tail(days)
    items = [
        {"date": str(r["date"]),
         "main_net_inflow": r["main_net_inflow"],
         "main_net_inflow_pct": r.get("main_net_inflow_pct"),
         "super_large_net": r["super_large_net"],
         "large_net": r["large_net"],
         "medium_net": r["medium_net"],
         "small_net": r["small_net"]}
        for r in df.to_dict(orient="records")
    ]
    return {"items": items}


@router.get("/statistics")
def statistics():
    """全市场涨跌统计（涨跌停按 stk_limit 价格比较）。"""
    fetcher = _fetcher()
    as_of = fetcher._as_of()
    try:
        df = fetcher.daily_with_limits(as_of)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"涨跌统计不可用: {exc}") from exc
    if df is None or df.empty:
        return {"as_of": yyyymmdd_to_iso(as_of) or as_of, "up": None, "note": "当日无数据"}
    close = pd.to_numeric(df["close"], errors="coerce") if "close" in df.columns else None
    # daily_with_limits 返回上游原始列（pct_chg）；缺列时用 close/pre_close 本地推导
    if "pct_change" in df.columns:
        pct = pd.to_numeric(df["pct_change"], errors="coerce")
    elif "pct_chg" in df.columns:
        pct = pd.to_numeric(df["pct_chg"], errors="coerce")
    elif "pre_close" in df.columns:
        pre = pd.to_numeric(df["pre_close"], errors="coerce")
        pct = (close / pre - 1) * 100
    else:
        return {"as_of": yyyymmdd_to_iso(as_of) or as_of, "total": int(len(df)),
                "up": None, "down": None, "flat": None,
                "note": "行情缺少涨跌幅字段"}
    pct = pct.where(close.notna() if close is not None else pct.notna())
    up = int((pct > 0).sum())
    down = int((pct < 0).sum())
    flat = int((pct == 0).sum())
    up_limit_col = "up_limit" if "up_limit" in df.columns else None
    down_limit_col = "down_limit" if "down_limit" in df.columns else None
    limit_up = limit_down = None
    if up_limit_col and close is not None and df["up_limit"].notna().any():
        limit_up = int((close >= pd.to_numeric(df["up_limit"], errors="coerce")).sum())
        limit_down = int((close <= pd.to_numeric(df["down_limit"], errors="coerce")).sum())
    return {
        "as_of": yyyymmdd_to_iso(as_of) or as_of,
        "total": int(len(df)),
        "up": up, "down": down, "flat": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "limit_by_price": bool(up_limit_col),
    }
