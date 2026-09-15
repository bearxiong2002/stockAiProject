"""Mock 数据源（阶段2 模拟数据，显式显式测试模式）。

保留阶段2 的确定性模拟生成逻辑与返回契约，仅作为 STOCK_DATA_MODE=mock
下的显式数据来源；真实模式下不参与任何业务路径（design.md §4.1.6）。
"""
from __future__ import annotations

import hashlib
import random
import time
from datetime import date, timedelta

import pandas as pd

from services.providers.normalize import (
    KLINE_COLUMNS,
    code_from_ts,
    resample_period,
    yyyymmdd_to_iso,
)

MOCK_STOCKS: list[dict] = [
    {"code": "600519", "name": "贵州茅台", "industry": "白酒", "market": "沪", "price": 1520.0, "float_shares": 12.56},
    {"code": "000858", "name": "五粮液", "industry": "白酒", "market": "深", "price": 128.0, "float_shares": 38.8},
    {"code": "601318", "name": "中国平安", "industry": "保险", "market": "沪", "price": 54.5, "float_shares": 148.0},
    {"code": "600036", "name": "招商银行", "industry": "银行", "market": "沪", "price": 41.5, "float_shares": 197.0},
    {"code": "000001", "name": "平安银行", "industry": "银行", "market": "深", "price": 11.8, "float_shares": 194.0},
    {"code": "600276", "name": "恒瑞医药", "industry": "医药", "market": "沪", "price": 52.0, "float_shares": 63.0},
    {"code": "300750", "name": "宁德时代", "industry": "电池", "market": "深", "price": 265.0, "float_shares": 19.5},
    {"code": "002594", "name": "比亚迪", "industry": "汽车", "market": "深", "price": 335.0, "float_shares": 29.0},
    {"code": "601899", "name": "紫金矿业", "industry": "有色金属", "market": "沪", "price": 19.5, "float_shares": 210.0},
    {"code": "600900", "name": "长江电力", "industry": "电力", "market": "沪", "price": 28.5, "float_shares": 200.0},
    {"code": "000333", "name": "美的集团", "industry": "家电", "market": "深", "price": 76.0, "float_shares": 69.0},
    {"code": "600690", "name": "海尔智家", "industry": "家电", "market": "沪", "price": 28.5, "float_shares": 60.0},
    {"code": "601012", "name": "隆基绿能", "industry": "光伏", "market": "沪", "price": 18.0, "float_shares": 72.0},
    {"code": "002415", "name": "海康威视", "industry": "安防", "market": "深", "price": 31.0, "float_shares": 92.0},
    {"code": "600030", "name": "中信证券", "industry": "证券", "market": "沪", "price": 28.0, "float_shares": 121.0},
    {"code": "601166", "name": "兴业银行", "industry": "银行", "market": "沪", "price": 20.5, "float_shares": 193.0},
    {"code": "000651", "name": "格力电器", "industry": "家电", "market": "深", "price": 45.0, "float_shares": 56.0},
    {"code": "600887", "name": "伊利股份", "industry": "食品", "market": "沪", "price": 28.0, "float_shares": 63.0},
    {"code": "601888", "name": "中国中免", "industry": "免税", "market": "沪", "price": 76.0, "float_shares": 20.0},
    {"code": "688981", "name": "中芯国际", "industry": "半导体", "market": "沪", "price": 92.0, "float_shares": 21.0},
    {"code": "300059", "name": "东方财富", "industry": "证券", "market": "深", "price": 25.0, "float_shares": 79.0},
    {"code": "002714", "name": "牧原股份", "industry": "农牧", "market": "深", "price": 43.0, "float_shares": 54.0},
]

_STOCK_INDEX = {s["code"]: s for s in MOCK_STOCKS}
INDUSTRY_BOARDS = ["白酒", "银行", "保险", "医药", "电池", "汽车", "有色金属", "电力",
                   "家电", "光伏", "安防", "证券", "食品", "免税", "半导体", "农牧",
                   "房地产", "军工", "计算机", "传媒"]
_INDEX_META = {
    "000001": {"name": "上证指数", "base": 3520.0, "suffix": "SH"},
    "399001": {"name": "深证成指", "base": 11200.0, "suffix": "SZ"},
    "399006": {"name": "创业板指", "base": 2250.0, "suffix": "SZ"},
    "000688": {"name": "科创50", "base": 980.0, "suffix": "SH"},
    "000300": {"name": "沪深300", "base": 4150.0, "suffix": "SH"},
}


def _rng(*parts: object) -> "random.Random":
    key = "|".join(str(p) for p in parts)
    return random.Random(int(hashlib.md5(key.encode("utf-8")).hexdigest()[:12], 16))


def _trade_dates(n: int, end: date | None = None) -> list[date]:
    d = end or date.today()
    out: list[date] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _quarter_ends(n: int) -> list[date]:
    import calendar
    today = date.today()
    month = ((today.month - 1) // 3) * 3 + 3
    year = today.year
    out: list[date] = []
    while len(out) < n:
        out.append(date(year, month, calendar.monthrange(year, month)[1]))
        month -= 3
        if month <= 0:
            month += 12
            year -= 1
    return sorted(out)


def _base_price(code: str) -> float:
    s = _STOCK_INDEX.get(code)
    if s:
        return s["price"]
    return round(_rng("price", code).uniform(5.0, 180.0), 2)


def _float_shares(code: str) -> float:
    s = _STOCK_INDEX.get(code)
    if s:
        return s["float_shares"]
    return round(_rng("float_shares", code).uniform(3.0, 80.0), 1)


def _stock_name(code: str) -> str:
    return _STOCK_INDEX[code]["name"] if code in _STOCK_INDEX else f"模拟{code}"


def _gen_closes(code: str, n: int = 250) -> list[float]:
    rng = _rng("kline", code)
    drift = rng.uniform(-0.0008, 0.0014)
    vol = rng.uniform(0.012, 0.028)
    rets = [rng.gauss(drift, vol) for _ in range(n)]
    cum = [1.0]
    for r in rets:
        cum.append(cum[-1] * (1 + r))
    base = _base_price(code)
    return [base * c / cum[-1] for c in cum[1:]]


def _meta(api: str, extra: dict | None = None) -> dict:
    meta = {"source": "mock", "provider": "mock", "api": api, "fetched_at": time.time()}
    if extra:
        meta.update(extra)
    return meta


class MockSource:
    """模拟数据源: 实现与真实 provider 相同的"归一化能力方法"。"""

    provider = "mock"

    # -- 基础行情 -----------------------------------------------------------

    def stock_list(self) -> tuple[pd.DataFrame, dict]:
        df = pd.DataFrame(
            [{"code": s["code"], "name": s["name"], "industry": s["industry"],
              "market": s["market"]} for s in MOCK_STOCKS],
            columns=["code", "name", "industry", "market"])
        return df, _meta("stock_basic")

    def kline(self, code: str, period: str = "daily", start_date: str | None = None,
              end_date: str | None = None, adjust: str = "qfq") -> tuple[pd.DataFrame, dict]:
        rng = _rng("ohlc", code)
        closes = _gen_closes(code, 250)
        dates = [d.isoformat() for d in _trade_dates(250)]
        float_shares = _float_shares(code)
        prev_close = closes[0] / (1 + _rng("kline", code).gauss(0, 0.02))
        rows = []
        for i, close in enumerate(closes):
            close = round(close, 2)
            open_px = round(prev_close * (1 + rng.uniform(-0.005, 0.005)), 2)
            high = round(max(open_px, close) * (1 + abs(rng.uniform(0, 0.008))), 2)
            low = round(min(open_px, close) * (1 - abs(rng.uniform(0, 0.008))), 2)
            change = round(close - prev_close, 2)
            pct_change = round(change / prev_close * 100, 2)
            amplitude = round((high - low) / prev_close * 100, 2)
            turnover = round(rng.uniform(4.0, 12.0), 2) if rng.random() < 0.06 else round(rng.uniform(0.2, 3.0), 2)
            vol_shares = turnover / 100 * float_shares * 1e8
            volume = int(vol_shares // 100)
            amount = round(vol_shares * (open_px + high + low + close) / 4, 2)
            rows.append({"date": dates[i], "open": open_px, "close": close, "high": high,
                         "low": low, "volume": volume, "amount": amount,
                         "amplitude": amplitude, "pct_change": pct_change,
                         "change": change, "turnover": turnover})
            prev_close = close
        df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
        df = resample_period(df, period)
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.reset_index(drop=True)
        trade_date = dates[-1]
        return df, _meta("daily", {"trade_date": trade_date, "adjust": adjust or "raw",
                                   "mock": True})

    def stock_info(self, code: str) -> tuple[dict, dict]:
        code = code.split(".")[0]  # 兼容裸码/ts_code 传参（mock 内部索引为 6 位裸码）
        kline, _ = self.kline(code, "daily")
        last = kline.iloc[-1]
        rng = _rng("info", code)
        float_shares = _float_shares(code)
        total_shares = round(float_shares * rng.uniform(1.0, 1.35), 2)
        price = float(last["close"])
        stock = _STOCK_INDEX.get(code)
        return {
            "code": code,
            "name": _stock_name(code),
            "industry": stock["industry"] if stock else "综合",
            "market": stock["market"] if stock else ("沪" if code.startswith(("6",)) else "深"),
            "list_date": None,
            "area": None,
            "market_cap": round(total_shares * price, 2),
            "float_market_cap": round(float_shares * price, 2),
            "pe": round(rng.uniform(8, 55) if price < 300 else rng.uniform(18, 45), 2),
            "pe_static": None,
            "pb": round(rng.uniform(0.8, 9.5), 2),
            "ps": None,
            "total_shares": total_shares,
            "float_shares": float_shares,
            "latest_price": price,
            "pct_change": float(last["pct_change"]),
            "trade_date": last["date"],
            "turnover": float(last["turnover"]),
        }, _meta("stock_basic", {"trade_date": str(last["date"]), "mock": True})

    def valuation(self, code: str) -> tuple[dict, dict]:
        rng = _rng("valuation", code)
        pe = round(rng.uniform(8, 55), 2)
        info, _ = self.stock_info(code)
        return {
            "pe_ttm": info.get("pe"), "pe_static": None, "pb": info.get("pb"),
            "ps": round(pe * rng.uniform(0.06, 0.2), 2), "pcf": None,
            "dividend_yield": round(rng.uniform(0, 5.5), 2),
            "market_cap": info.get("market_cap"),
            "latest_price": info.get("latest_price"),
            "trade_date": info.get("trade_date"),
        }, _meta("daily_basic", {"mock": True})

    # -- 财务 ---------------------------------------------------------------

    def fina_indicator(self, code: str) -> tuple[pd.DataFrame, dict]:
        rng0 = _rng("fin", code)
        gross = rng0.uniform(15, 62)
        debt = rng0.uniform(20, 66)
        roe_base = rng0.uniform(6, 30)
        rev_base = rng0.uniform(-5, 28)
        rows = []
        for qe in _quarter_ends(8):
            r = _rng("fin", code, qe)
            gross_margin = round(gross + r.uniform(-2, 2), 2)
            roe = round(roe_base + r.uniform(-3, 3), 2)
            revenue_growth = round(rev_base + r.uniform(-6, 6), 2)
            rows.append({
                "date": qe.isoformat(), "ann_date": (qe + timedelta(days=60)).isoformat(),
                "roe": roe, "roa": round(roe * r.uniform(0.25, 0.45), 2),
                "gross_margin": gross_margin,
                "net_margin": round(gross_margin * r.uniform(0.25, 0.6), 2),
                "revenue_growth": revenue_growth,
                "profit_growth": round(revenue_growth * r.uniform(0.5, 1.8), 2),
                "debt_ratio": round(debt + r.uniform(-3, 3), 2),
                "eps": round(max(roe, 0.5) * r.uniform(0.1, 0.35), 2),
                "bps": round(r.uniform(2, 32), 2),
                "current_ratio": round(r.uniform(1.0, 4.0), 2),
            })
        import pandas as pd
        return pd.DataFrame(rows), _meta("fina_indicator", {"mock": True})

    def income(self, code: str) -> tuple[pd.DataFrame, dict]:
        return self._sheet(code, "income")

    def balance_sheet(self, code: str) -> tuple[pd.DataFrame, dict]:
        return self._sheet(code, "balance")

    def cashflow_sheet(self, code: str) -> tuple[pd.DataFrame, dict]:
        return self._sheet(code, "cashflow")

    def _sheet(self, code: str, kind: str) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import CASHFLOW_MAP, INCOME_MAP, BALANCE_MAP  # noqa
        rng0 = _rng(kind, code)
        mapping = {"income": INCOME_MAP, "balance": BALANCE_MAP, "cashflow": CASHFLOW_MAP}[kind]
        rows = []
        scale = rng0.uniform(30, 900) * 1e8
        for i, qe in enumerate(_quarter_ends(8)):
            r = _rng(kind, code, qe)
            base = scale * (1 + 0.02 * (7 - i))
            if kind == "income":
                vals = {"OPERATE_INCOME": base * 0.98, "TOTAL_REVENUE": base,
                        "OPERATE_COST": base * 0.4, "OPERATE_PROFIT": base * 0.42,
                        "TOTAL_PROFIT": base * 0.43, "INCOME_TAX": base * 0.09,
                        "NETPROFIT": base * 0.34, "PARENT_NETPROFIT": base * 0.34}
            elif kind == "balance":
                vals = {"TOTAL_ASSETS": base * 1.8, "TOTAL_LIABILITIES": base * 0.8,
                        "TOTAL_EQUITY": base, "MONETARYFUNDS": base * 0.35,
                        "ACCOUNTS_RECE": base * 0.15, "INVENTORY": base * 0.3,
                        "CURRENT_ASSETS": base * 1.0}
            else:
                vals = {"NETCASH_OPERATE": base * 0.4, "NETCASH_INVEST": -base * 0.2,
                        "NETCASH_FINANCE": -base * 0.1, "CCE_ADD": base * 0.1}
            rows.append({"REPORT_DATE": qe.isoformat(),
                         "ANN_DATE": (qe + timedelta(days=60)).isoformat(),
                         "F_ANN_DATE": (qe + timedelta(days=62)).isoformat(),
                         **vals})
        return pd.DataFrame(rows), _meta(kind, {"mock": True})

    def holder_info(self, code: str) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        rng = _rng("holder", code)
        names = ["香港中央结算有限公司", "中国证券金融股份有限公司", "中央汇金资产管理有限责任公司",
                 "全国社保基金一零一组合", "易方达沪深300ETF", "招商中证白酒指数分级",
                 "华夏上证50ETF", "高毅邻山1号远望基金", "新加坡政府投资有限公司", "阿布达比投资局"]
        total = _float_shares(code) * 1e4
        remaining = 55.0
        rows = []
        for i, hname in enumerate(names):
            pct_ = remaining * rng.uniform(0.08, 0.3)
            remaining -= pct_
            rows.append({"股东名称": hname, "持股数量": round(total * pct_ / 100, 2),
                         "持股比例": round(pct_, 2), "股东排名": i + 1,
                         "报告期": _quarter_ends(1)[0].isoformat(),
                         "公告日期": (_quarter_ends(1)[0] + timedelta(days=45)).isoformat()})
        return pd.DataFrame(rows), _meta("top10_holders", {"mock": True})

    def dividend_history(self, code: str) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        rng = _rng("dividend", code)
        rows = []
        for qe in _quarter_ends(12):
            if rng.random() < 0.5:
                continue
            rows.append({"report_date": qe.isoformat(),
                         "dividend": round(rng.uniform(0, 3.5), 2),
                         "stock_bonus": rng.choice([0, 0, 0, 1, 2]),
                         "stock_transfer": rng.choice([0, 0, 0, 2, 3]),
                         "ex_date": (qe + timedelta(days=75)).isoformat(),
                         "ann_date": (qe + timedelta(days=10)).isoformat()})
        return pd.DataFrame(rows), _meta("dividend", {"mock": True})

    # -- 资金 ---------------------------------------------------------------

    def fund_flow(self, code: str) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import FUND_FLOW_COLUMNS
        dates = [d.isoformat() for d in _trade_dates(30)]
        rng = _rng("fundflow", code)
        trend = rng.uniform(-0.6, 0.7)
        level = 0.0
        rows = []
        for d in dates:
            level = level * 0.7 + trend + rng.gauss(0, 0.9)
            main = round(max(level, -3.5), 2)
            super_large = round(main * rng.uniform(0.35, 0.65), 2)
            large = round(main - super_large, 2)
            medium = round(-main * rng.uniform(0.4, 0.7), 2)
            small = round(-main - medium, 2)
            rows.append({"date": d, "main_net_inflow": main,
                         "main_net_inflow_pct": round(rng.uniform(-8, 8), 2),
                         "super_large_net": super_large, "large_net": large,
                         "medium_net": medium, "small_net": small})
        return pd.DataFrame(rows, columns=FUND_FLOW_COLUMNS), _meta("moneyflow", {"mock": True})

    def market_fund_flow(self) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import FUND_FLOW_COLUMNS
        dates = [d.isoformat() for d in _trade_dates(30)]
        rng = _rng("marketflow")
        level = 0.0
        rows = []
        for d in dates:
            level = level * 0.6 + rng.gauss(0, 35)
            main = round(max(min(level, 180), -180), 1)
            super_large = round(main * rng.uniform(0.3, 0.6), 1)
            large = round(main - super_large, 1)
            medium = round(-main * rng.uniform(0.35, 0.65), 1)
            small = round(-main - medium, 1)
            rows.append({"date": d, "main_net_inflow": main,
                         "main_net_inflow_pct": round(rng.uniform(-2.5, 2.5), 2),
                         "super_large_net": super_large, "large_net": large,
                         "medium_net": medium, "small_net": small})
        return pd.DataFrame(rows, columns=FUND_FLOW_COLUMNS), _meta("moneyflow_mkt_dc", {"mock": True})

    # -- 指数与板块 ---------------------------------------------------------

    def index_data(self, index_code: str = "000001", period: str = "daily") -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import INDEX_COLUMNS
        meta = _INDEX_META.get(index_code, {"name": index_code, "base": 3000.0, "suffix": "SH"})
        rng = _rng("index", index_code)
        n = 250
        dates = [d.isoformat() for d in _trade_dates(n)]
        drift = rng.uniform(-0.0004, 0.0008)
        rets = [rng.gauss(drift, 0.012) for _ in range(n)]
        cum = [1.0]
        for r in rets:
            cum.append(cum[-1] * (1 + r))
        scale = meta["base"] / cum[-1]
        rows = []
        prev = scale
        for i in range(n):
            close = cum[i + 1] * scale
            open_px = prev * (1 + rng.uniform(-0.003, 0.003))
            high = max(open_px, close) * (1 + abs(rng.uniform(0, 0.005)))
            low = min(open_px, close) * (1 - abs(rng.uniform(0, 0.005)))
            rows.append({"date": dates[i], "open": round(open_px, 2), "close": round(close, 2),
                         "high": round(high, 2), "low": round(low, 2),
                         "volume": int(rng.uniform(1.5e8, 5e8)),
                         "amount": round(rng.uniform(2500, 9000) * 1e8, 2)})
            prev = close
        df = pd.DataFrame(rows, columns=INDEX_COLUMNS)
        df = resample_period(df, period) if period != "daily" else df
        return df, _meta("index_daily", {"mock": True, "ts_code": f"{index_code}.{meta['suffix']}"})

    def board_list(self) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import BOARD_COLUMNS
        rows = []
        for name in INDUSTRY_BOARDS:
            r = _rng("board", name)
            lead = next((s for s in MOCK_STOCKS if s["industry"] == name), None)
            rows.append({"name": name,
                         "code": f"BK{_rng('bk', name).randint(1000, 9999)}",
                         "pct_change": round(r.uniform(-2.8, 3.6), 2),
                         "turnover": round(r.uniform(40, 800), 2),
                         "leading_stock": lead["name"] if lead else f"{name}龙头",
                         "leading_pct": round(r.uniform(2, 10), 2)})
        return pd.DataFrame(rows, columns=BOARD_COLUMNS), _meta("index_classify", {"mock": True})

    def industry_pe_pb(self, industry: str) -> tuple[dict, dict]:
        rng = _rng("industrype", industry)
        pe_median = round(rng.uniform(10, 45), 2)
        pb_median = round(rng.uniform(0.8, 6.0), 2)
        return ({"pe_median": pe_median, "pb_median": pb_median,
                 "pe_mean": round(pe_median * rng.uniform(0.9, 1.2), 2),
                 "pb_mean": round(pb_median * rng.uniform(0.9, 1.2), 2),
                 "stock_count": int(rng.uniform(20, 120))},
                _meta("index_member_all", {"mock": True}))

    def news(self, code: str) -> tuple[pd.DataFrame, dict]:
        import pandas as pd
        from services.providers.normalize import NEWS_COLUMNS
        name = _stock_name(code)
        today = date.today()
        templates = [
            ("{n}发布2026年半年度报告，营业收入同比增长",
             "{n}今日发布半年报，营收与净利润保持增长，经营性现金流改善明显。"),
            ("机构调研{n}：产能利用率维持高位",
             "多家机构近期调研{n}，管理层表示主要产品产能利用率维持高位。"),
            ("{n}获多家券商维持买入评级",
             "近期多家券商发布研报，维持对{n}的买入评级并上调目标价。"),
            ("{n}与上下游伙伴签署战略合作协议",
             "{n}公告与产业链上下游企业签署长期战略合作协议。"),
            ("{n}股东计划减持不超过2%股份",
             "{n}公告称部分股东因自身资金需求，拟减持不超过总股本2%。"),
        ]
        rng = _rng("news", code)
        sources = ["证券时报", "财联社", "新浪财经", "东方财富网", "上海证券报", "每日经济新闻"]
        rows = []
        for i in range(10):
            t_title, t_content = templates[i % len(templates)]
            day = today - timedelta(days=i // 2)
            rows.append({"title": t_title.format(n=name),
                         "content": t_content.format(n=name),
                         "pub_time": f"{day.isoformat()} {9 + (i * 7) % 9:02d}:{(i * 17) % 60:02d}",
                         "source": sources[rng.randrange(len(sources))]})
        return (pd.DataFrame(rows, columns=NEWS_COLUMNS),
                _meta("news", {"mock": True,
                               "warnings": ["模拟新闻数据，仅用于界面开发"]}))
