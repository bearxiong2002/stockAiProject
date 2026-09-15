"""字段映射、单位换算与契约归一化（design.md §4.1.4–§4.1.5）。

单位换算基于阶段3 真实数据校准（详见 docs/api-integration-validation.md）:
    股票 daily.vol: 手 → volume 股 ×100；daily.amount: 千元 → 元 ×1000
    指数 index_daily.amount: 千元 → 元 ×1000；vol 为股（沪市总额交叉验证）
    daily_basic.total_mv/circ_mv: 万元 → 亿元 ÷10000；total/float_share 万股 → 亿股 ÷10000
    个股 moneyflow.*_amount: 万元 → 亿元 ÷10000；moneyflow_mkt_dc: 元 → 亿元 ÷1e8
    sw_daily.amount: 万元 → 亿元 ÷10000（31行业合计≈全市场校准）；vol 保留原值并注明
    dividend.cash_div/stk_*: 每股口径 → 每10股 ×10（茅台2023年报 30.876 元/股实证）
    top10_holders.hold_amount: 股 → 万股 ÷10000（供应商返回字符串，需数字化）
"""
from __future__ import annotations

import math

import pandas as pd

KLINE_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount",
                 "amplitude", "pct_change", "change", "turnover"]
INDEX_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount"]
SHEET_BASE = ["REPORT_DATE", "ANN_DATE", "F_ANN_DATE"]
FUND_FLOW_COLUMNS = ["date", "main_net_inflow", "main_net_inflow_pct",
                     "super_large_net", "large_net", "medium_net", "small_net"]


# ---------------------------------------------------------------------------
# 代码 / 日期 / 数值
# ---------------------------------------------------------------------------

def market_of_ts(ts_code: str) -> str:
    suffix = str(ts_code).rsplit(".", 1)[-1].upper()
    return {"SH": "沪", "SZ": "深", "BJ": "北"}.get(suffix, suffix)


def code_from_ts(ts_code: str) -> str:
    return str(ts_code).rsplit(".", 1)[0]


def ts_code_of(code: str, *, asset: str = "stock") -> str:
    """六位代码 → 供应商 ts_code；指数与股票分流，不混用。"""
    code = str(code).strip()
    if "." in code:
        return code.upper()
    if asset == "index":
        return f"{code}.SH" if code.startswith(("000", "880", "950")) else f"{code}.SZ"
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    if code.startswith(("00", "30")):
        return f"{code}.SZ"
    if code.startswith(("43", "82", "83", "87", "88", "92")):
        return f"{code}.BJ"
    raise ValueError(f"无法识别的证券代码: {code}")


def iso_to_yyyymmdd(d: str | None) -> str | None:
    if not d:
        return None
    return str(d).replace("-", "")


def yyyymmdd_to_iso(d) -> str | None:
    if d is None or d == "":
        return None
    s = str(d).replace("-", "")
    if len(s) != 8 or not s.isdigit():
        return str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def num(value):
    """数值化: 字符串/None/NaN 统一处理；失败返回 None（缺测不是 0）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def pct(value):
    """百分数字段: 保持百分数值（1.25 = 1.25%），缺测 None。"""
    return num(value)


def to_df(fields: list[str], rows: list[list], columns: list[str] | None = None) -> pd.DataFrame:
    """供应商行 → DataFrame；成功空数组 → 带目标列的空表。"""
    if rows:
        return pd.DataFrame(rows, columns=[str(f) for f in fields])
    return pd.DataFrame(columns=columns or [str(f) for f in fields])


def dedup_latest(df: pd.DataFrame, key_cols: list[str], order_col: str | None) -> pd.DataFrame:
    """按 key 分组保留 order_col 最大（最新公告/修订）行。"""
    if df.empty:
        return df
    if order_col and order_col in df.columns:
        df = df.sort_values(order_col)
    return df.groupby(key_cols, as_index=False).tail(1).sort_values(key_cols).reset_index(drop=True)


# ---------------------------------------------------------------------------
# K 线（daily + daily_basic + adj_factor → 11 列契约）
# ---------------------------------------------------------------------------

def build_kline(raw_daily: pd.DataFrame, raw_basic: pd.DataFrame | None,
                raw_adj: pd.DataFrame | None, *, adjust: str,
                visible_from: str | None = None) -> pd.DataFrame:
    """合并为 K 线契约（升序）。adjust: "" 未复权 / qfq / hfq。

    复权: 前复权 P×F(t)/F(anchor)，anchor=窗口内最近有效因子；后复权 P×F(t)。
    缺因子抛 ValueError，由上层转为明确不可用，不悄悄返回未复权价。
    """
    if raw_daily.empty:
        return pd.DataFrame(columns=KLINE_COLUMNS)
    df = raw_daily.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df["volume"] = (df["vol"].map(num) * 100).round().astype("Int64")
    df["amount"] = (df["amount"].map(num) * 1000).round(2)
    df["turnover"] = None
    if raw_basic is not None and not raw_basic.empty:
        basic = raw_basic[["trade_date", "turnover_rate"]].copy()
        basic["trade_date"] = basic["trade_date"].astype(str)
        df = df.merge(basic, on="trade_date", how="left", suffixes=("", "_b"))
        df["turnover"] = df["turnover_rate"].map(pct)

    if adjust in ("qfq", "hfq"):
        if raw_adj is None or raw_adj.empty:
            raise ValueError("复权因子缺失，无法返回复权价格")
        adj = raw_adj[["trade_date", "adj_factor"]].copy()
        adj["trade_date"] = adj["trade_date"].astype(str)
        adj["adj_factor"] = adj["adj_factor"].map(num)
        df = df.merge(adj, on="trade_date", how="inner")
        if df.empty:
            raise ValueError("复权因子与日线无交集")
        # 分窗合并后行序不可控: 先按日期升序，anchor = 截止范围内最近有效因子
        df = df.sort_values("trade_date").reset_index(drop=True)
        anchor = float(df.iloc[-1]["adj_factor"])
        factor = df["adj_factor"] / (anchor if adjust == "qfq" else 1.0)
        for col in ("open", "high", "low", "close", "pre_close", "change"):
            df[col] = (df[col].map(num) * factor).round(4)

    out = pd.DataFrame({
        "date": df["trade_date"].map(yyyymmdd_to_iso),
        "open": df["open"], "close": df["close"], "high": df["high"], "low": df["low"],
        "volume": df["volume"], "amount": df["amount"],
        "amplitude": ((df["high"].map(num) - df["low"].map(num))
                      / df["pre_close"].map(num) * 100).round(4),
        "pct_change": df["pct_chg"].map(pct),
        "change": df["change"],
        "turnover": df["turnover"],
    }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if visible_from:
        out = out[out["date"] >= visible_from].reset_index(drop=True)
    return out[KLINE_COLUMNS]


def resample_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """已复权日线 → 周（ISO 周）/月（自然月）聚合；涨跌幅按上一周期末收。

    turnover 为日换手率之和；不完整周期由调用方在 meta 标注。
    """
    if period in ("daily", "") or df.empty:
        return df
    out = df.copy()
    dt = pd.to_datetime(out["date"])
    out["_key"] = dt.dt.strftime("%G-%V") if period == "weekly" else out["date"].str[:7]

    def _sum(grp, col):
        # 显式接收分组数据，避免闭包捕获外层循环变量
        if col not in out.columns:
            return None
        s = pd.Series(grp[col])
        return None if s.isna().all() else round(float(s.fillna(0).sum()), 4)

    rows = []
    prev_close: float | None = None
    for _, g in out.groupby("_key", sort=True):
        first, last = g.iloc[0], g.iloc[-1]
        close = float(last["close"])
        ref = prev_close if prev_close is not None else float(first["open"])
        rows.append({
            "date": last["date"],
            "open": round(float(first["open"]), 4),
            "close": round(close, 4),
            "high": round(float(g["high"].max()), 4),
            "low": round(float(g["low"].min()), 4),
            "volume": (int(pd.Series(g["volume"]).fillna(0).astype("int64").sum())
                       if "volume" in g.columns else None),
            "amount": (round(float(pd.Series(g["amount"]).fillna(0).sum()), 2)
                       if "amount" in g.columns else None),
            "amplitude": round((float(g["high"].max()) - float(g["low"].min())) / ref * 100, 4)
            if ref else None,
            "pct_change": round((close - ref) / ref * 100, 4) if ref else None,
            "change": round(close - ref, 4) if ref is not None else None,
            "turnover": _sum(g, "turnover"),
        })
        prev_close = close
    return pd.DataFrame(rows, columns=df.columns.tolist())


# ---------------------------------------------------------------------------
# 列表 / 信息 / 估值
# ---------------------------------------------------------------------------

def stock_list_df(raw: pd.DataFrame) -> pd.DataFrame:
    """stock_basic → code/name/industry/market 契约。"""
    if raw.empty:
        return pd.DataFrame(columns=["code", "name", "industry", "market"])
    code_col = "symbol" if "symbol" in raw.columns else raw["ts_code"].map(code_from_ts)
    industry = (raw["industry"].fillna("综合").astype(str)
                if "industry" in raw.columns else pd.Series("综合", index=raw.index))
    return pd.DataFrame({
        "code": raw["symbol"].astype(str) if "symbol" in raw.columns else raw["ts_code"].map(code_from_ts),
        "name": raw["name"].astype(str),
        "industry": industry,
        "market": raw["ts_code"].map(market_of_ts),
    })


def stock_info_dict(basic_row: dict, daily_row: dict | None, basic_day: dict | None) -> dict:
    """stock_basic 行 + 未复权最近日线 + 同日 daily_basic → get_stock_info 契约。

    dict 入参（行记录 dict），市值亿元、股本亿股（万元/万股 ÷10000）。
    """
    info: dict = {
        "code": code_from_ts(basic_row.get("ts_code", "")),
        "name": str(basic_row.get("name") or ""),
        "industry": basic_row.get("industry") or "综合",
        "market": market_of_ts(str(basic_row.get("ts_code", ""))),
        "area": basic_row.get("area"),
        "list_date": yyyymmdd_to_iso(basic_row.get("list_date")),
        "latest_price": None, "pct_change": None, "trade_date": None,
        "market_cap": None, "float_market_cap": None,
        "pe": None, "pe_static": None, "pb": None, "ps": None,
        "total_shares": None, "float_shares": None, "turnover": None,
    }
    if daily_row:
        info["latest_price"] = num(daily_row.get("close"))
        info["pct_change"] = pct(daily_row.get("pct_chg"))
        info["trade_date"] = yyyymmdd_to_iso(daily_row.get("trade_date"))
    if basic_day:
        info["market_cap"] = _wan_to_yi(basic_day.get("total_mv"))
        info["float_market_cap"] = _wan_to_yi(basic_day.get("circ_mv"))
        info["pe"] = pct(basic_day.get("pe_ttm"))
        info["pe_static"] = pct(basic_day.get("pe"))
        info["pb"] = pct(basic_day.get("pb"))
        info["ps"] = pct(basic_day.get("ps_ttm") or basic_day.get("ps"))
        total_share = num(basic_day.get("total_share"))
        float_share = num(basic_day.get("float_share"))
        info["total_shares"] = round(total_share / 1e4, 4) if total_share is not None else None
        info["float_shares"] = round(float_share / 1e4, 4) if float_share is not None else None
        info["turnover"] = pct(basic_day.get("turnover_rate"))
    return info


def _wan_to_yi(v) -> float | None:
    n = num(v)
    return round(n / 1e4, 2) if n is not None else None


def valuation_dict(basic_day: dict | None, daily_row: dict | None) -> dict:
    """daily_basic + 未复权收盘 → get_stock_valuation。PCF 缺口径返回 null。"""
    if not basic_day:
        return {"pe_ttm": None, "pe_static": None, "pb": None, "ps": None,
                "pcf": None, "dividend_yield": None, "market_cap": None,
                "trade_date": None if not daily_row else yyyymmdd_to_iso(daily_row.get("trade_date")),
                "latest_price": None if not daily_row else num(daily_row.get("close"))}
    out = {
        "pe_ttm": pct(basic_day.get("pe_ttm")),
        "pe_static": pct(basic_day.get("pe")),
        "pb": pct(basic_day.get("pb")),
        "ps": pct(basic_day.get("ps_ttm") or basic_day.get("ps")),
        "pcf": None,  # 经营现金流 TTM 与市值口径一致才可推导，否则 null
        "dividend_yield": pct(basic_day.get("dv_ttm") or basic_day.get("dv_ratio")),
        "market_cap": _wan_to_yi(basic_day.get("total_mv")),
    }
    if daily_row:
        out["latest_price"] = num(daily_row.get("close"))
        out["trade_date"] = yyyymmdd_to_iso(daily_row.get("trade_date"))
    return out


# ---------------------------------------------------------------------------
# 财务
# ---------------------------------------------------------------------------

FINA_MAP = {  # 源字段 → 契约列（百分数保持百分数值）
    "roe": "roe", "roa": "roa",
    "grossprofit_margin": "gross_margin", "netprofit_margin": "net_margin",
    "or_yoy": "revenue_growth", "netprofit_yoy": "profit_growth",
    "debt_to_assets": "debt_ratio", "eps": "eps", "bps": "bps",
    "current_ratio": "current_ratio",
}
FINA_COLUMNS = ["date", "ann_date"] + list(FINA_MAP.values())

INCOME_MAP = {
    "revenue": "OPERATE_INCOME", "total_revenue": "TOTAL_REVENUE",
    "oper_cost": "OPERATE_COST", "operate_profit": "OPERATE_PROFIT",
    "total_profit": "TOTAL_PROFIT", "income_tax": "INCOME_TAX",
    "n_income": "NETPROFIT", "n_income_attr_p": "PARENT_NETPROFIT",
}
BALANCE_MAP = {
    "total_assets": "TOTAL_ASSETS", "total_liab": "TOTAL_LIABILITIES",
    "total_hldr_eqy_exc_min_int": "TOTAL_EQUITY", "money_cap": "MONETARYFUNDS",
    "accounts_receiv": "ACCOUNTS_RECE", "inventories": "INVENTORY",
    "total_cur_assets": "CURRENT_ASSETS",
}
CASHFLOW_MAP = {
    "n_cashflow_act": "NETCASH_OPERATE", "n_cashflow_inv_act": "NETCASH_INVEST",
    "n_cash_flows_fnc_act": "NETCASH_FINANCE", "n_incr_cash_cash_equ": "CCE_ADD",
}


def fina_indicator_df(raw: pd.DataFrame) -> pd.DataFrame:
    """fina_indicator → 契约；同一报告期保留最新公告版本（修订可见性）。"""
    if raw.empty:
        return pd.DataFrame(columns=FINA_COLUMNS)
    df = raw.copy()
    out = pd.DataFrame(index=df.index)
    out["date"] = df["end_date"].map(yyyymmdd_to_iso)
    out["ann_date"] = df["ann_date"].map(yyyymmdd_to_iso) if "ann_date" in df.columns else None
    for src, dst in FINA_MAP.items():
        out[dst] = df[src].map(pct) if src in df.columns else None
    out = out.dropna(subset=["date"])
    return dedup_latest(out, ["date"], "ann_date").sort_values("date").reset_index(drop=True)


def _report_df(raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    cols = SHEET_BASE + list(mapping.values())
    if raw.empty:
        return pd.DataFrame(columns=cols)
    df = raw.copy()
    if "report_type" in df.columns:
        df = df[df["report_type"].astype(str) == "1"]  # 合并报表口径
    out = pd.DataFrame(index=df.index)
    out["REPORT_DATE"] = df["end_date"].map(yyyymmdd_to_iso)
    out["ANN_DATE"] = df["ann_date"].map(yyyymmdd_to_iso) if "ann_date" in df.columns else None
    out["F_ANN_DATE"] = df["f_ann_date"].map(yyyymmdd_to_iso) if "f_ann_date" in df.columns else None
    for src, dst in mapping.items():
        out[dst] = df[src].map(num) if src in df.columns else None
    out = out.dropna(subset=["REPORT_DATE"])
    return dedup_latest(out, ["REPORT_DATE"], "F_ANN_DATE").sort_values("REPORT_DATE").reset_index(drop=True)


def income_df(raw: pd.DataFrame) -> pd.DataFrame:
    return _report_df(raw, INCOME_MAP)


def balance_df(raw: pd.DataFrame) -> pd.DataFrame:
    return _report_df(raw, BALANCE_MAP)


def cashflow_df(raw: pd.DataFrame) -> pd.DataFrame:
    return _report_df(raw, CASHFLOW_MAP)


# ---------------------------------------------------------------------------
# 资金流
# ---------------------------------------------------------------------------

def _size_diff(df: pd.DataFrame, size: str) -> pd.Series:
    buy = df[f"buy_{size}_amount"].map(num) if f"buy_{size}_amount" in df.columns else None
    sell = df[f"sell_{size}_amount"].map(num) if f"sell_{size}_amount" in df.columns else None
    if buy is None or sell is None:
        return pd.Series([None] * len(df), index=df.index)
    return ((buy - sell) / 1e4).round(4)  # 万元 → 亿元


def moneyflow_df(raw: pd.DataFrame, amount_by_date: pd.DataFrame | None = None) -> pd.DataFrame:
    """个股 moneyflow（万元）→ 四类单 + 主力净额（亿元）。

    主力 = 超大单(elg)+大单(lg) 净额；main_net_inflow_pct = 主力/同日成交额×100（缺失 null）。
    """
    if raw.empty:
        return pd.DataFrame(columns=FUND_FLOW_COLUMNS)
    df = raw.copy()
    df["date"] = df["trade_date"].map(yyyymmdd_to_iso)
    df["super_large_net"] = _size_diff(df, "elg")
    df["large_net"] = _size_diff(df, "lg")
    df["medium_net"] = _size_diff(df, "md")
    df["small_net"] = _size_diff(df, "sm")
    # 缺测不是 0：超大单与大单任一缺失 → 主力净额 null
    main = pd.to_numeric(df["super_large_net"], errors="coerce") \
        + pd.to_numeric(df["large_net"], errors="coerce")
    df["main_net_inflow"] = main.where(
        pd.to_numeric(df["super_large_net"], errors="coerce").notna()
        & pd.to_numeric(df["large_net"], errors="coerce").notna())
    df["main_net_inflow_pct"] = None
    if amount_by_date is not None and not amount_by_date.empty:
        df = df.merge(amount_by_date, on="date", how="left")
        # main_net_inflow 单位亿元，amount_yuan 单位元 → ×1e8 对齐
        df["main_net_inflow_pct"] = df.apply(
            lambda r: round(r["main_net_inflow"] * 1e8 / r["amount_yuan"] * 100, 4)
            if r.get("amount_yuan") else None, axis=1)
    return df[FUND_FLOW_COLUMNS].sort_values("date").reset_index(drop=True)


def mkt_fund_flow_df(raw: pd.DataFrame) -> pd.DataFrame:
    """moneyflow_mkt_dc（元）→ 大盘资金契约（亿元）。主力净额 = net_amount。"""
    if raw.empty:
        return pd.DataFrame(columns=FUND_FLOW_COLUMNS)
    df = raw.copy()
    df["date"] = df["trade_date"].map(yyyymmdd_to_iso)
    for src, dst in (("net_amount", "main_net_inflow"), ("buy_elg_amount", "super_large_net"),
                     ("buy_lg_amount", "large_net"), ("buy_md_amount", "medium_net"),
                     ("buy_sm_amount", "small_net")):
        df[dst] = (df[src].map(num) / 1e8).round(4) if src in df.columns else None
    df["main_net_inflow_pct"] = (df["net_amount_rate"].map(pct)
                                 if "net_amount_rate" in df.columns else None)
    return df[FUND_FLOW_COLUMNS].sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 指数 / 行业
# ---------------------------------------------------------------------------

def index_df(raw: pd.DataFrame) -> pd.DataFrame:
    """index_daily → date/open/close/high/low/volume(股)/amount(元)。"""
    if raw.empty:
        return pd.DataFrame(columns=INDEX_COLUMNS)
    df = raw.copy()
    out = pd.DataFrame({
        "date": df["trade_date"].map(yyyymmdd_to_iso),
        "open": df["open"].map(num), "close": df["close"].map(num),
        "high": df["high"].map(num), "low": df["low"].map(num),
        "volume": df["vol"].map(num),
        "amount": (df["amount"].map(num) * 1000).round(2),
    }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


BOARD_COLUMNS = ["name", "code", "pct_change", "turnover", "leading_stock", "leading_pct"]


def board_list_df(classify: pd.DataFrame, sw_latest: dict[str, dict] | None = None,
                  leading_by_industry: dict[str, dict] | None = None) -> pd.DataFrame:
    """申万 L1 分类 + 当日 sw_daily → 行业板块列表契约。

    turnover = 成交额（亿元，sw_daily.amount 万元 ÷ 1e4）；sw vol 单位不解释、不入列。
    """
    if classify.empty:
        return pd.DataFrame(columns=BOARD_COLUMNS)
    df = (classify[classify["level"].astype(str) == "L1"]
          if "level" in classify.columns else classify).copy()
    rows = []
    for _, r in df.iterrows():
        code = str(r["index_code"])
        sw = (sw_latest or {}).get(code, {})
        lead = (leading_by_industry or {}).get(code, {})
        rows.append({
            "name": str(r["industry_name"]),
            "code": code,
            "pct_change": pct(sw.get("pct_change")),
            "turnover": round(num(sw.get("amount")) / 1e4, 2)
            if num(sw.get("amount")) is not None else None,
            "leading_stock": lead.get("name"),
            "leading_pct": lead.get("pct_change"),
        })
    return pd.DataFrame(rows, columns=BOARD_COLUMNS)


def holder_df(raw: pd.DataFrame) -> pd.DataFrame:
    """top10_holders（hold_amount 股，字符串）→ 中文列契约（万股），按持股数量排名。"""
    cols = ["股东名称", "持股数量", "持股比例", "股东排名", "报告期", "公告日期"]
    if raw.empty:
        return pd.DataFrame(columns=cols)
    df = raw.copy()
    df["_amount"] = df["hold_amount"].map(num)
    df = df.dropna(subset=["_amount"])
    # 仅最近一期可见报告（多期混行时按最新 end_date 过滤）
    latest_end = str(df["end_date"].max()) if "end_date" in df.columns else None
    if latest_end and "end_date" in df.columns:
        df = df[df["end_date"].astype(str) == latest_end]
    df = df.sort_values("_amount", ascending=False).reset_index(drop=True)
    out = pd.DataFrame({
        "股东名称": df["holder_name"].astype(str),
        "持股数量": (df["_amount"] / 1e4).round(2),
        "持股比例": df["hold_ratio"].map(pct) if "hold_ratio" in df.columns else None,
        "股东排名": range(1, len(df) + 1),
        "报告期": df["end_date"].map(yyyymmdd_to_iso) if "end_date" in df.columns else None,
        "公告日期": df["ann_date"].map(yyyymmdd_to_iso) if "ann_date" in df.columns else None,
    })
    return out


def dividend_df(raw: pd.DataFrame) -> pd.DataFrame:
    """dividend → 仅"实施"完成分红；每股口径 ×10 换算为每10股。"""
    cols = ["report_date", "dividend", "stock_bonus", "stock_transfer", "ex_date", "ann_date"]
    if raw.empty:
        return pd.DataFrame(columns=cols)
    df = raw[raw["div_proc"].astype(str) == "实施"].copy()
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("ann_date").groupby("end_date", as_index=False).tail(1)
    out = pd.DataFrame({
        "report_date": df["end_date"].map(yyyymmdd_to_iso),
        "dividend": (df["cash_div"].map(num) * 10).round(4),
        "stock_bonus": (df["stk_bo_rate"].map(num) * 10).round(4),
        "stock_transfer": (df["stk_co_rate"].map(num) * 10).round(4),
        "ex_date": df["ex_date"].map(yyyymmdd_to_iso),
        "ann_date": df["ann_date"].map(yyyymmdd_to_iso),
    }).dropna(subset=["report_date"])
    return out.sort_values("report_date").reset_index(drop=True)


def industry_pe_pb_dict(members: pd.DataFrame, basic_day: pd.DataFrame) -> dict:
    """行业成员 ∩ 同日 daily_basic → PE/PB 统计（正有效样本，含样本数与覆盖率）。"""
    out = {"pe_median": None, "pb_median": None, "pe_mean": None, "pb_mean": None,
           "stock_count": 0}
    if members.empty or basic_day is None or basic_day.empty:
        out["warning"] = "行业成分或当日 daily_basic 缺失"
        return out
    joined = members.merge(basic_day, on="ts_code", how="inner")
    if joined.empty:
        out["warning"] = "行业成分与当日估值无交集"
        return out
    pe = joined["pe_ttm"].map(num) if "pe_ttm" in joined.columns else pd.Series(dtype=float)
    pb = joined["pb"].map(num) if "pb" in joined.columns else None
    pe_pos = pe[pe > 0].dropna()
    out["stock_count"] = int(len(joined))
    out["pe_sample_count"] = int(len(pe_pos))
    out["pe_coverage"] = round(len(pe_pos) / len(joined), 4)
    if not pe_pos.empty:
        out["pe_median"] = round(float(pe_pos.median()), 4)
        out["pe_mean"] = round(float(pe_pos.mean()), 4)
    if pb is not None and not pb.empty:
        pb_pos = pb[pb > 0].dropna()
        out["pb_sample_count"] = int(len(pb_pos))
        out["pb_coverage"] = round(len(pb_pos) / len(joined), 4)
        if not pb_pos.empty:
            out["pb_median"] = round(float(pb_pos.median()), 4)
            out["pb_mean"] = round(float(pb_pos.mean()), 4)
    return out


# ---------------------------------------------------------------------------
# 新闻关联
# ---------------------------------------------------------------------------

NEWS_COLUMNS = ["title", "content", "pub_time", "source"]


def news_df(raw: pd.DataFrame, stock_name: str | None) -> pd.DataFrame:
    """新闻原始数据 → 本地个股关联（名称证据）、去重、ISO 时间。

    无可靠关联返回空表（市场新闻不当作个股新闻）。
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=NEWS_COLUMNS)
    df = raw.copy()
    title_col = next((c for c in ("title", "digest") if c in df.columns), None)
    if title_col is None:
        return pd.DataFrame(columns=NEWS_COLUMNS)
    content_col = "content" if "content" in df.columns else title_col
    if stock_name:
        kw = stock_name.replace(" ", "")
        mask = (df[title_col].astype(str).str.contains(kw, regex=False, na=False)
                | df[content_col].astype(str).str.contains(kw, regex=False, na=False))
        df = df[mask]
    if df.empty:
        return pd.DataFrame(columns=NEWS_COLUMNS)
    df = df.drop_duplicates(subset=[title_col])
    time_col = next((c for c in ("pub_time", "datetime", "publish_time", "time")
                     if c in df.columns), None)
    out = pd.DataFrame({
        "title": df[title_col].astype(str),
        "content": df[content_col].astype(str) if content_col in df.columns else "",
        "pub_time": df[time_col].astype(str) if time_col else None,
        "source": df["src"].astype(str) if "src" in df.columns else "news",
    })
    return out.head(20).reset_index(drop=True)
