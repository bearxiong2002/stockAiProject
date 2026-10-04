"""DataFetcher — 统一数据入口（阶段3: 双源真实数据路由）。

保持阶段2 的 17 个方法契约（参数与返回结构不变），内部按 STOCK_DATA_MODE 路由:
    mock       → providers.mock.MockSource（显式模拟）
    datahubco  → providers.datahubco.DatahubcoSource（仅主源，失败即报错）
    promax     → providers.promax.ProMaxSource（仅备用源）
    hybrid     → 按 design.md §4.1.4 固定主备链路（仅可恢复故障才换源）

核心数据（列表/K线/信息/估值/财务/指数）失败抛 DataSourceError（路由层映射 HTTP）；
可选数据（新闻/资金/行业/股东/分红）失败返回空数据 + 明确 warning，不回退模拟。
缓存: services.cache.run_cached（mode 目录隔离 + _data_meta + stale 回退）。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from config import settings
from services.cache import cache_key, run_cached
from services.providers.datahubco import DatahubcoSource
from services.providers.errors import (
    DataSourceError,
    DataSourceParamError,
    DataSourceUnavailableError,
)
from services.providers.mock import MockSource
from services.providers.normalize import (
    BOARD_COLUMNS,
    FUND_FLOW_COLUMNS,
    FINA_MAP,
    KLINE_COLUMNS,
    NEWS_COLUMNS,
    balance_df,
    board_list_df,
    build_kline,
    cashflow_df,
    code_from_ts,
    dividend_df,
    fina_indicator_df,
    holder_df,
    income_df,
    index_df,
    industry_pe_pb_dict,
    iso_to_yyyymmdd,
    mkt_fund_flow_df,
    moneyflow_df,
    news_df,
    num,
    resample_period,
    stock_info_dict,
    stock_list_df,
    ts_code_of,
    valuation_dict,
    yyyymmdd_to_iso,
)
from services.providers.promax import ProMaxSource

logger = logging.getLogger("stockpanel.data")

CN_TZ = timezone(timedelta(hours=8))
# 行情 15-17 点、资金流 19 点发布 → 19:30 后才把当日视为"已发布"
PUBLISH_CUTOFF_HOUR = 19
INDEX_TS_MAP = {  # 指数与股票分流，000001.SZ 股票 / 000001.SH 指数不混用
    "000001": ("000001.SH", "上证指数"),
    "399001": ("399001.SZ", "深证成指"),
    "399006": ("399006.SZ", "创业板指"),
    "000688": ("000688.SH", "科创50"),
    "000300": ("000300.SH", "沪深300"),
}
NEWS_SOURCE = "cls"  # 仅验证过的取值（eastmoney/sina 忽略日期参数）
NEWS_WINDOW_DAYS = 3
# 上游超 limit 直接截断（按时间升序取最早 N 条、offset 无效）；cls 快讯工作日约 150~180 条/天
NEWS_FETCH_LIMIT = 2000
# ProMax 网关冷缓存（X-Cache=MISS）首次返回 code=0 空结果，稍后同参数重试才命中（2026-09-13 实测）
NEWS_EMPTY_RETRY_DELAY = 8.0
DEFAULT_LOOKBACK_DAYS = 420   # ≈285 交易日，保证 MA250/251 个价格点
LOOKBACK_PAD_DAYS = 10        # 复权首行 change 的窗口前哨

_shared_fetcher: DataFetcher | None = None
_shared_lock = threading.Lock()


def get_data_fetcher() -> DataFetcher:
    """进程级共享 DataFetcher（复用 HTTP 连接池；mock/real 由环境决定）。"""
    global _shared_fetcher
    if _shared_fetcher is None:
        with _shared_lock:
            if _shared_fetcher is None:
                _shared_fetcher = DataFetcher()
    return _shared_fetcher


class DataFetcher:
    """统一数据入口；方法同步阻塞（FastAPI 同步路由自动进线程池）。"""

    def __init__(self, mode: str | None = None):
        self.mode = (mode or settings.STOCK_DATA_MODE).strip().lower()
        if self.mode not in ("mock", "datahubco", "promax", "hybrid"):
            raise DataSourceParamError(f"未知数据源模式: {self.mode}")
        self._mock = MockSource()
        self._real: dict[str, object] = {}  # 真实客户端按需懒加载（mock 模式不建连接池）
        self._mem: dict[str, tuple[float, object]] = {}
        self._mem_lock = threading.Lock()

    @property
    def _dh(self):
        src_obj = self._real.get("datahubco")
        if src_obj is None:
            src_obj = self._real["datahubco"] = DatahubcoSource()
        return src_obj

    @property
    def _pm(self):
        src_obj = self._real.get("promax")
        if src_obj is None:
            src_obj = self._real["promax"] = ProMaxSource()
        return src_obj

    def close(self) -> None:
        """释放已创建的真实 HTTP 客户端连接池（进程退出/测试收尾调用）。"""
        for src_obj in self._real.values():
            closer = getattr(src_obj, "close", None)
            if callable(closer):
                closer()
        self._real.clear()

    @property
    def primary(self) -> str:
        """hybrid 主源；单源模式即自身。"""
        if self.mode == "hybrid":
            return "datahubco"
        return self.mode

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _now_cn(self) -> datetime:
        return datetime.now(CN_TZ)

    @staticmethod
    def _shift(end_yyyymmdd: str, days: int) -> str:
        d = datetime.strptime(end_yyyymmdd, "%Y%m%d") - timedelta(days=days)
        return d.strftime("%Y%m%d")

    def _as_of(self) -> str:
        """最近已完成且上游已发布的交易日（YYYYMMDD）。"""
        with self._mem_lock:
            cached = self._mem.get("as_of")
            if cached and time.time() - cached[0] < 600:
                return str(cached[1])
        now = self._now_cn()
        today = now.strftime("%Y%m%d")
        days = self._trade_days(60)
        latest = days[-1] if days else today
        if latest == today and now.hour < PUBLISH_CUTOFF_HOUR:
            earlier = [d for d in days if d < today]
            latest = earlier[-1] if earlier else latest
        with self._mem_lock:
            self._mem["as_of"] = (time.time(), latest)
        return latest

    def _trade_days(self, n_back: int = 400) -> list[str]:
        """开市日列表（升序）；12h 内存缓存 + 文件缓存。"""
        with self._mem_lock:
            cached = self._mem.get("trade_days")
            if cached and time.time() - cached[0] < 12 * 3600:
                return list(cached[1])
        end = self._now_cn().strftime("%Y%m%d")
        start = self._shift(end, n_back)

        def produce():
            res = self._dh.trade_cal(start, end)
            opens = sorted(str(r[1]) for r in res.rows if str(r[2]) == "1")
            df = pd.DataFrame({"cal_date": opens})
            meta = {"source": res.provider, "api": "trade_cal", "as_of": end,
                    "fetched_at": res.fetched_at, "trade_date": opens[-1] if opens else None,
                    "is_stale": False, "warnings": res.warnings or []}
            return df, meta

        try:
            df, _meta, _ = run_cached(
                self.mode, "calendar", "trade_days",
                cache_key(self.mode, "trade_cal", {"span": n_back}),
                settings.CACHE_TTL_DAILY, produce)
            days = [str(x) for x in df["cal_date"].tolist()] if not df.empty else []
        except DataSourceError:
            if self.mode == "mock":
                days = [d.strftime("%Y%m%d") for d in _mock_trade_days(n_back)]
            else:
                raise
        with self._mem_lock:
            self._mem["trade_days"] = (time.time(), days)
        return days

    def _df(self, fetch) -> pd.DataFrame:
        return pd.DataFrame(fetch.rows, columns=fetch.fields) if fetch.rows else \
            pd.DataFrame(columns=fetch.fields)

    def _meta(self, fetch, api: str, *, trade_date=None, coverage=None,
              warnings=None) -> dict:
        meta = {
            "source": getattr(fetch, "provider", "unknown"),
            "api": api,
            "as_of": self._as_of(),
            "trade_date": trade_date,
            "fetched_at": getattr(fetch, "fetched_at", None) or time.time(),
            "is_stale": False,
            "request_id": getattr(fetch, "request_id", None),
            "coverage": coverage,
            "pages": getattr(fetch, "pages", 1),
        }
        ws = list(getattr(fetch, "warnings", None) or []) + list(warnings or [])
        if ws:
            meta["warnings"] = ws
        return meta

    def _attach(self, result, meta: dict):
        if isinstance(result, pd.DataFrame):
            result.attrs["data_meta"] = meta
        elif isinstance(result, dict):
            result["_data_meta"] = meta
        return result

    def _run_mock_cached(self, subdir: str, name: str | None, key: str, ttl: float,
                         mock_call: Callable):
        """mock 模式同样走文件缓存（阶段2 检查点: 缓存写入/读取/过期）。"""
        def producer():
            result, meta = mock_call()
            return result, {**meta, "as_of": self._as_of()}
        result, meta, _ = run_cached(self.mode, subdir, name, key, ttl, producer)
        return result, meta

    # ------------------------------------------------------------------
    # 路由模板
    # ------------------------------------------------------------------

    def _route(self, dh_produce: Callable, pm_produce: Callable | None = None, *,
               dh_name: str = "datahubco", pm_name: str = "promax"):
        """hybrid: 主源 → 仅可恢复故障才试备用源；认证/权限/参数/协议错误直接报。

        dh_name/pm_name 仅用于日志标注实际出错的数据源（个别能力的主备函数
        可能与默认主备源不同，如 promax 专属能力）。
        """
        if self.mode == "datahubco":
            return dh_produce()
        if self.mode == "promax":
            if pm_produce is None:
                raise DataSourceParamError("promax 模式缺少该能力的实现")
            return pm_produce()
        last_exc: DataSourceError | None = None
        attempts: list[tuple[str, Callable]] = [(dh_name, dh_produce)]
        if pm_produce is not None:
            attempts.append((pm_name, pm_produce))
        for provider, fn in attempts:
            try:
                return fn()
            except DataSourceError as exc:
                last_exc = exc
                if not exc.retryable:
                    raise  # 不跨源试错（design.md §4.1.3 冲突处理）
                logger.warning("%s 可恢复故障，尝试备用源: %s", provider, exc.message)
        raise last_exc  # type: ignore[misc]

    def _route_optional(self, dh_produce, pm_produce, fallback: Callable | None, *,
                        dh_name: str = "datahubco", pm_name: str = "promax"):
        """可选能力: 主备失败 → fallback() 返回空数据 + 明确 warning。"""
        try:
            return self._route(dh_produce, pm_produce, dh_name=dh_name, pm_name=pm_name)
        except DataSourceError as exc:
            if fallback is not None:
                logger.warning("可选能力降级: %s", exc.message)
                return fallback()
            raise

    def _check_source(self, provider: str) -> None:
        """真实模式缺密钥/HTTP 未允许 → 明确配置错误（不静默降级 mock）。"""
        if self.mode == "mock":
            return
        source = {"datahubco": self._dh, "promax": self._pm}[provider]
        problems = source.config_problems()
        if problems and self.mode in (provider, "hybrid"):
            raise DataSourceUnavailableError(
                f"{provider} 配置不可用: " + "; ".join(problems),
                provider=provider, api=None)

    # ------------------------------------------------------------------
    # 1. get_stock_list
    # ------------------------------------------------------------------

    def get_stock_list(self) -> pd.DataFrame:
        """全部 A 股（沪深北、list_status=L、去重）+ 申万一级行业补齐。"""

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.stock_list_page(paginate=True)
            df = stock_list_df(self._df(fetch))
            return self._finalize_list(fetch, df)

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.stock_list_page(paginate=True)
            df = stock_list_df(self._df(fetch))
            return self._finalize_list(fetch, df)

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "", "stock_list", cache_key(self.mode, "get_stock_list", {}),
                settings.CACHE_TTL_DAILY, self._mock.stock_list)
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "", "stock_list", cache_key(self.mode, "get_stock_list", {}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(df, meta)

    def _finalize_list(self, fetch, df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
        before = len(df)
        df = df.drop_duplicates(subset=["code"]).reset_index(drop=True)
        df = self._attach_industry(df)
        meta = self._meta(fetch, "stock_basic", trade_date=None, coverage=len(df),
                          warnings=(list(fetch.warnings or []) +
                                    ([f"重复代码 {before - len(df)} 行已去重"] if before > len(df) else [])))
        df.attrs["data_meta"] = meta
        return df, meta

    def _attach_industry(self, df: pd.DataFrame) -> pd.DataFrame:
        """申万2021 一级行业补齐（成分表可用时覆盖供应商 industry）。"""
        try:
            member_map = self._industry_membership()
        except DataSourceError:
            member_map = {}
        if not member_map:
            meta = df.attrs.get("data_meta", {})
            meta["warnings"] = list(meta.get("warnings") or []) + \
                ["申万行业成分不可用，industry 保留供应商分类"]
            df.attrs["data_meta"] = meta
            return df
        l1 = df["code"].map(lambda c: (member_map.get(f"{c}.SH")
                                       or member_map.get(f"{c}.SZ")
                                       or member_map.get(f"{c}.BJ") or {}).get("l1_name"))
        covered = int(l1.notna().sum())
        df["industry"] = l1.fillna(df["industry"].astype(str))
        meta = df.attrs.get("data_meta", {})
        meta["industry_coverage"] = round(covered / len(df), 4) if len(df) else None
        df.attrs["data_meta"] = meta
        return df

    def _industry_membership(self) -> dict[str, dict]:
        """全市场申万成分映射（ts_code → l1_*），7 天文件缓存。"""

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.index_member_all(paginate=True)
            return self._membership_from(fetch)

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.index_member_all(paginate=True)
            return self._membership_from(fetch)

        mapping, meta, _ = run_cached(
            self.mode, "financial", "sw_member_all",
            cache_key(self.mode, "sw_member_all", {}),
            settings.CACHE_TTL_FINANCIAL,
            lambda: self._route(produce_dh, produce_pm))
        return mapping if isinstance(mapping, dict) else {}

    def _membership_from(self, fetch) -> tuple[dict, dict]:
        raw = self._df(fetch)
        mapping: dict[str, dict] = {}
        for row in raw.to_dict(orient="records"):
            if row.get("out_date"):
                continue
            mapping[str(row["ts_code"])] = {
                "l1_code": row.get("l1_code"), "l1_name": row.get("l1_name")}
        meta = self._meta(fetch, "index_member_all", trade_date=None,
                          coverage=len(mapping), warnings=fetch.warnings or [])
        return mapping, meta

    # ------------------------------------------------------------------
    # 2. get_kline
    # ------------------------------------------------------------------

    def get_kline(self, code: str, period: str = "daily", start_date: str | None = None,
                  end_date: str | None = None, adjust: str = "qfq") -> pd.DataFrame:
        """历史K线契约 11 列；qfq/hfq 基于 adj_factor 本地复权。"""
        if period not in ("daily", "weekly", "monthly"):
            raise DataSourceParamError(f"不支持的 period: {period}")
        if adjust not in ("", "qfq", "hfq"):
            raise DataSourceParamError(f"不支持的 adjust: {adjust}")
        ts = ts_code_of(code)
        as_of = self._as_of()
        end = iso_to_yyyymmdd(end_date) or as_of
        start = iso_to_yyyymmdd(start_date) or self._shift(end, DEFAULT_LOOKBACK_DAYS)
        params = {"code": ts, "period": period, "start": start, "end": end,
                  "adjust": adjust}
        fetch_start = self._shift(start, LOOKBACK_PAD_DAYS)  # 首行 change 前哨

        def _kline_from(source) -> tuple[pd.DataFrame, dict]:
            fetch = source.daily(ts, start_date=fetch_start, end_date=end)
            daily = self._df(fetch)
            fetch_basic = source.daily_basic(ts, start_date=start, end_date=end)
            basic = self._df(fetch_basic)
            fetch_adj = source.adj_factor(ts, fetch_start, end) if adjust else None
            adj = self._df(fetch_adj) if fetch_adj is not None else None
            kline = build_kline(daily, basic, adj, adjust=adjust,
                                visible_from=yyyymmdd_to_iso(start))
            kline = resample_period(kline, period)
            warnings = list(fetch.warnings or [])
            if adjust and (adj is None or adj.empty):
                raise DataSourceUnavailableError(
                    "复权因子缺失，无法返回复权价格", provider=fetch.provider, api="adj_factor")
            anchor = str(adj.iloc[-1]["adj_factor"]) if (adj is not None and len(adj)) else None
            meta = self._meta(fetch, "daily+daily_basic+adj_factor",
                              trade_date=str(kline["date"].iloc[-1]) if len(kline) else None,
                              coverage=len(kline), warnings=warnings)
            meta["adjust"] = adjust or "raw"
            meta["anchor"] = anchor
            return kline, meta

        def produce_dh():
            self._check_source("datahubco")
            return _kline_from(self._dh)

        def produce_pm():
            self._check_source("promax")
            return _kline_from(self._pm)

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "kline", None, cache_key(self.mode, "get_kline", params),
                settings.CACHE_TTL_KLINE,
                lambda: self._mock.kline(code, period, yyyymmdd_to_iso(start),
                                         yyyymmdd_to_iso(end), adjust))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "kline", None,
            cache_key(self.mode, "get_kline", params), settings.CACHE_TTL_KLINE,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 3. get_stock_info
    # ------------------------------------------------------------------

    def get_stock_info(self, code: str) -> dict:
        """个股基本信息: stock_basic + 未复权最近收盘 + 同日 daily_basic。"""
        ts = ts_code_of(code)
        as_of = self._as_of()

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.stock_basic_row(ts)
            raw = self._df(fetch)
            if raw.empty:
                fetch = self._dh.stock_basic_row(ts, list_status="D")
                raw = self._df(fetch)
            daily_f = self._dh.daily(ts, start_date=self._shift(as_of, 15), end_date=as_of)
            daily = self._df(daily_f)
            daily_row = self._last_row(daily, "trade_date")
            basic = self._df(self._dh.daily_basic(
                ts, trade_date=(daily_row or {}).get("trade_date")))
            info = stock_info_dict(self._first_row(raw), daily_row,
                                   self._first_row(basic))
            return info, self._meta(fetch, "stock_basic+daily+daily_basic",
                                    trade_date=info.get("trade_date"))

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.stock_basic_row(ts)
            raw = self._df(fetch)
            if raw.empty:
                fetch = self._pm.stock_basic_row(ts, list_status="D")
                raw = self._df(fetch)
            daily_f = self._pm.daily(ts, start_date=self._shift(as_of, 15), end_date=as_of)
            daily = self._df(daily_f)
            daily_row = self._last_row(daily, "trade_date")
            basic = self._df(self._pm.daily_basic(
                ts, trade_date=(daily_row or {}).get("trade_date")))
            info = stock_info_dict(self._first_row(raw), daily_row, self._first_row(basic))
            return info, self._meta(fetch, "stock_basic+daily+daily_basic",
                                    trade_date=info.get("trade_date"))

        if self.mode == "mock":
            info, meta = self._run_mock_cached(
                "info", None,
                cache_key(self.mode, "get_stock_info", {"code": ts, "as_of": as_of}),
                settings.CACHE_TTL_DAILY, lambda: self._mock.stock_info(code))
            return self._attach(info, meta)

        info, meta, _ = run_cached(
            self.mode, "info", None,
            cache_key(self.mode, "get_stock_info", {"code": ts, "as_of": as_of}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(info, meta)

    @staticmethod
    def _first_row(df: pd.DataFrame) -> dict | None:
        return df.iloc[0].to_dict() if not df.empty else None

    @staticmethod
    def _last_row(df: pd.DataFrame, by: str) -> dict | None:
        if df.empty:
            return None
        return df.sort_values(by).iloc[-1].to_dict()

    # ------------------------------------------------------------------
    # 4. get_stock_valuation
    # ------------------------------------------------------------------

    def get_stock_valuation(self, code: str) -> dict:
        """同日估值（PE/PB/PS/股息率/市值）；PCF 无一致口径 → null。"""
        ts = ts_code_of(code)
        as_of = self._as_of()

        def produce_dh():
            self._check_source("datahubco")
            daily_f = self._dh.daily(ts, start_date=self._shift(as_of, 15), end_date=as_of)
            daily = self._df(daily_f)
            trade_date = (self._last_row(daily, "trade_date") or {}).get("trade_date")
            basic_f = self._dh.daily_basic(ts, trade_date=trade_date)
            basic = self._df(basic_f)
            val = valuation_dict(self._first_row(basic), self._last_row(daily, "trade_date"))
            return val, self._meta(basic_f, "daily_basic+daily", trade_date=val.get("trade_date"))

        def produce_pm():
            self._check_source("promax")
            daily_f = self._pm.daily(ts, start_date=self._shift(as_of, 15), end_date=as_of)
            daily = self._df(daily_f)
            trade_date = (self._last_row(daily, "trade_date") or {}).get("trade_date")
            basic_f = self._pm.daily_basic(ts, trade_date=trade_date)
            basic = self._df(basic_f)
            val = valuation_dict(self._first_row(basic), self._last_row(daily, "trade_date"))
            return val, self._meta(basic_f, "daily_basic+daily", trade_date=val.get("trade_date"))

        if self.mode == "mock":
            val, meta = self._run_mock_cached(
                "info", None,
                cache_key(self.mode, "get_stock_valuation", {"code": ts, "as_of": as_of}),
                settings.CACHE_TTL_DAILY, lambda: self._mock.valuation(code))
            return self._attach(val, meta)

        val, meta, _ = run_cached(
            self.mode, "info", None,
            cache_key(self.mode, "get_stock_valuation", {"code": ts, "as_of": as_of}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(val, meta)

    # ------------------------------------------------------------------
    # 5. get_financial_indicator
    # ------------------------------------------------------------------

    def get_financial_indicator(self, code: str) -> pd.DataFrame:
        """财务指标（最近 8 期已披露；同报告期保留最新公告版本）。"""
        ts = ts_code_of(code)

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.fina_indicator(ts)
            raw = self._df(fetch)
            df = fina_indicator_df(raw)
            df = df.tail(8).reset_index(drop=True)
            meta = self._meta(fetch, "fina_indicator",
                              trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                              coverage=len(df),
                              warnings=_missing_fields(FINA_MAP, raw))
            return df, meta

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.fina_indicator(ts)
            raw = self._df(fetch)
            df = fina_indicator_df(raw).tail(8).reset_index(drop=True)
            return df, self._meta(fetch, "fina_indicator",
                                  trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                                  coverage=len(df))

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "financial", None,
                cache_key(self.mode, "get_financial_indicator", {"code": ts}),
                settings.CACHE_TTL_FINANCIAL, lambda: self._mock.fina_indicator(code))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "financial", None,
            cache_key(self.mode, "get_financial_indicator", {"code": ts}),
            settings.CACHE_TTL_FINANCIAL,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 6-8. 三大报表
    # ------------------------------------------------------------------

    def get_profit_sheet(self, code: str) -> pd.DataFrame:
        return self._sheet("get_profit_sheet", code, income_df,
                           ("OPERATE_INCOME", "OPERATE_COST", "OPERATE_PROFIT",
                            "TOTAL_PROFIT", "INCOME_TAX", "NETPROFIT", "PARENT_NETPROFIT"))

    def get_balance_sheet(self, code: str) -> pd.DataFrame:
        return self._sheet("get_balance_sheet", code, balance_df,
                           ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY",
                            "MONETARYFUNDS", "ACCOUNTS_RECE", "INVENTORY", "CURRENT_ASSETS"))

    def get_cashflow_sheet(self, code: str) -> pd.DataFrame:
        return self._sheet("get_cashflow_sheet", code, cashflow_df,
                           ("NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE", "CCE_ADD"))

    def _sheet(self, method: str, code: str, transform, keep_cols) -> pd.DataFrame:
        ts = ts_code_of(code)
        api = {"get_profit_sheet": "income", "get_balance_sheet": "balancesheet",
               "get_cashflow_sheet": "cashflow"}[method]

        def produce_dh():
            self._check_source("datahubco")
            fetch = getattr(self._dh, api)(ts)
            df = transform(self._df(fetch)).tail(8).reset_index(drop=True)
            return df, self._meta(fetch, api,
                                  trade_date=str(df["REPORT_DATE"].iloc[-1]) if len(df) else None,
                                  coverage=len(df))

        def produce_pm():
            self._check_source("promax")
            fetch = getattr(self._pm, api)(ts)
            df = transform(self._df(fetch)).tail(8).reset_index(drop=True)
            return df, self._meta(fetch, api,
                                  trade_date=str(df["REPORT_DATE"].iloc[-1]) if len(df) else None,
                                  coverage=len(df))

        if self.mode == "mock":
            mock_map = {"get_profit_sheet": self._mock.income,
                        "get_balance_sheet": self._mock.balance_sheet,
                        "get_cashflow_sheet": self._mock.cashflow_sheet}
            df, meta = self._run_mock_cached(
                "financial", None, cache_key(self.mode, method, {"code": ts}),
                settings.CACHE_TTL_FINANCIAL, lambda: mock_map[method](code))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "financial", None,
            cache_key(self.mode, method, {"code": ts}),
            settings.CACHE_TTL_FINANCIAL,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 9. get_holder_info（ProMax 专属）
    # ------------------------------------------------------------------

    def get_holder_info(self, code: str) -> pd.DataFrame:
        ts = ts_code_of(code)

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.top10_holders(ts)
            df = holder_df(self._df(fetch)).head(10).reset_index(drop=True)
            meta = self._meta(fetch, "top10_holders",
                              trade_date=(df["报告期"].iloc[0] if len(df) else None))
            return df, meta

        def fallback():
            return pd.DataFrame(columns=["股东名称", "持股数量", "持股比例", "股东排名",
                                         "报告期", "公告日期"]), \
                {"source": "unavailable", "provider": "promax", "api": "top10_holders",
                 "as_of": self._as_of(), "is_stale": False,
                 "warnings": ["十大股东暂不可用（ProMax 专属能力获取失败）"]}

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "financial", None,
                cache_key(self.mode, "get_holder_info", {"code": ts}),
                settings.CACHE_TTL_FINANCIAL, lambda: self._mock.holder_info(code))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "financial", None,
            cache_key(self.mode, "get_holder_info", {"code": ts}),
            settings.CACHE_TTL_FINANCIAL,
            lambda: self._route_optional(produce_pm, None, fallback,
                                         dh_name="promax/top10_holders"))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 10. get_dividend_history
    # ------------------------------------------------------------------

    def get_dividend_history(self, code: str) -> pd.DataFrame:
        ts = ts_code_of(code)

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.dividend(ts)
            df = dividend_df(self._df(fetch))
            return df, self._meta(fetch, "dividend",
                                  trade_date=str(df["report_date"].iloc[-1]) if len(df) else None,
                                  coverage=len(df))

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.dividend(ts)
            df = dividend_df(self._df(fetch))
            return df, self._meta(fetch, "dividend",
                                  trade_date=str(df["report_date"].iloc[-1]) if len(df) else None)

        def fallback():
            return pd.DataFrame(columns=["report_date", "dividend", "stock_bonus",
                                         "stock_transfer", "ex_date", "ann_date"]), \
                {"source": "unavailable", "api": "dividend", "as_of": self._as_of(),
                 "warnings": ["分红历史暂不可用"]}

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "financial", None,
                cache_key(self.mode, "get_dividend_history", {"code": ts}),
                settings.CACHE_TTL_FINANCIAL, lambda: self._mock.dividend_history(code))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "financial", None,
            cache_key(self.mode, "get_dividend_history", {"code": ts}),
            settings.CACHE_TTL_FINANCIAL,
            lambda: self._route_optional(produce_dh, produce_pm, fallback))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 11. get_fund_flow（可选能力）
    # ------------------------------------------------------------------

    def get_fund_flow(self, code: str) -> pd.DataFrame:
        ts = ts_code_of(code)
        as_of = self._as_of()
        start = self._shift(as_of, 60)

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.moneyflow(ts, start, as_of)
            df = moneyflow_df(self._df(fetch),
                              self._daily_amounts_by_date(ts, start, as_of))
            df = df.tail(30).reset_index(drop=True)
            return df, self._meta(fetch, "moneyflow+daily",
                                  trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                                  coverage=len(df))

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.moneyflow(ts, start, as_of)
            df = moneyflow_df(self._df(fetch),
                              self._daily_amounts_by_date(ts, start, as_of))
            df = df.tail(30).reset_index(drop=True)
            return df, self._meta(fetch, "moneyflow+daily",
                                  trade_date=str(df["date"].iloc[-1]) if len(df) else None)

        def fallback():
            return pd.DataFrame(columns=FUND_FLOW_COLUMNS), {
                "source": "unavailable", "api": "moneyflow", "as_of": as_of,
                "warnings": ["个股资金流暂不可用"]}

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "kline", None,
                cache_key(self.mode, "get_fund_flow", {"code": ts, "as_of": as_of}),
                settings.CACHE_TTL_KLINE, lambda: self._mock.fund_flow(code))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "kline", None,
            cache_key(self.mode, "get_fund_flow", {"code": ts, "as_of": as_of}),
            settings.CACHE_TTL_KLINE,
            lambda: self._route_optional(produce_dh, produce_pm, fallback))
        return self._attach(df, meta)

    def _daily_amounts_by_date(self, ts: str, start: str, end: str) -> pd.DataFrame:
        """该股票区间日线成交额（元）→ 资金流 pct 分母（主力净额/成交额×100）。"""

        def produce_dh():
            fetch = self._dh.daily(ts_code=ts, start_date=start, end_date=end)
            raw = self._df(fetch)
            return self._amounts_df(raw), self._meta(fetch, "daily", trade_date=end)

        def produce_pm():
            fetch = self._pm.daily(ts_code=ts, start_date=start, end_date=end)
            raw = self._df(fetch)
            return self._amounts_df(raw), self._meta(fetch, "daily", trade_date=end)

        raw, meta, _ = run_cached(
            self.mode, "kline", None,
            cache_key(self.mode, "daily_amounts", {"ts": ts, "start": start, "end": end}),
            settings.CACHE_TTL_KLINE,
            lambda: self._route(produce_dh, produce_pm))
        raw.attrs["data_meta"] = meta
        return raw

    @staticmethod
    def _amounts_df(raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(columns=["date", "amount_yuan"])
        out = pd.DataFrame({
            "date": raw["trade_date"].map(yyyymmdd_to_iso),
            "amount_yuan": raw["amount"].map(lambda v: (num(v) or 0) * 1000),
        }).groupby("date", as_index=False).sum()
        return out

    # ------------------------------------------------------------------
    # 12. get_chip_distribution（筹码分布；仅 ProMax 支持）
    # ------------------------------------------------------------------

    def get_chip_distribution(self, code: str, trade_date: str | None = None) -> dict:
        """获取筹码分布数据。返回 {trade_date, items: [{price, percent}], perf: {...}}。"""
        ts = ts_code_of(code)
        if not trade_date:
            trade_date = self._as_of()

        self._check_source("promax")
        chips_fetch = self._pm.cyq_chips(ts, trade_date)
        chips_df = self._df(chips_fetch)

        if chips_df.empty:
            return {"trade_date": trade_date, "items": [], "perf": None}

        items = []
        for _, row in chips_df.iterrows():
            p = num(row.get("price"))
            pct = num(row.get("percent"))
            if p is not None and pct is not None:
                items.append({"price": round(p, 2), "percent": round(pct, 4)})
        items.sort(key=lambda x: x["price"])

        perf = None
        try:
            perf_fetch = self._pm.cyq_perf(ts, trade_date)
            perf_df = self._df(perf_fetch)
            if not perf_df.empty:
                r = perf_df.iloc[0]
                perf = {
                    "cost_5pct": num(r.get("cost_5pct")),
                    "cost_15pct": num(r.get("cost_15pct")),
                    "cost_85pct": num(r.get("cost_85pct")),
                    "cost_95pct": num(r.get("cost_95pct")),
                    "weight_avg": num(r.get("weight_avg")),
                    "winner_rate": num(r.get("winner_rate")),
                }
        except Exception:
            pass

        return {"trade_date": trade_date, "items": items, "perf": perf}

    # ------------------------------------------------------------------
    # 13. get_stock_news（可选能力；无关联新闻 → 空表 + warning）
    # ------------------------------------------------------------------

    def get_stock_news(self, code: str) -> pd.DataFrame:
        ts = ts_code_of(code)
        try:
            name = self._stock_name_of(ts)
        except DataSourceError:
            name = None
        end = self._now_cn().strftime("%Y-%m-%d %H:%M:%S")
        start = (self._now_cn() - timedelta(days=NEWS_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

        def produce_pm():
            fetch = self._pm.news(NEWS_SOURCE, start, end, limit=NEWS_FETCH_LIMIT)
            if not fetch.rows:
                # 冷缓存空结果：同一组参数再请求一次以命中网关缓存
                time.sleep(NEWS_EMPTY_RETRY_DELAY)
                fetch = self._pm.news(NEWS_SOURCE, start, end, limit=NEWS_FETCH_LIMIT)
            df = news_df(self._df(fetch), name)
            meta = self._meta(fetch, f"news({NEWS_SOURCE})", trade_date=end[:10],
                              coverage=len(df))
            if not fetch.rows:
                warning = "上游新闻源窗口内无数据（空结果已重试 1 次）"
            elif df.empty:
                warning = f"窗口内 {len(fetch.rows)} 条快讯均未提及该股"
            else:
                warning = None
            if warning:
                meta["warnings"] = list(meta.get("warnings") or []) + [warning]
            return df, meta

        def produce_major():
            fetch = self._pm.major_news(NEWS_SOURCE, start, end)
            df = news_df(self._df(fetch), name)
            return df, self._meta(fetch, f"major_news({NEWS_SOURCE})", trade_date=end[:10])

        def fallback():
            df = pd.DataFrame(columns=NEWS_COLUMNS)
            return df, {"source": "unavailable", "provider": "promax", "api": "news",
                        "as_of": self._as_of(), "is_stale": False,
                        "warnings": ["新闻数据暂不可用，个股新闻情绪将降级为无数据"]}

        if self.mode == "mock":
            df, meta = self._mock.news(code)  # 新闻不缓存（阶段2 契约）
            return self._attach(df, meta)
        if self.mode == "datahubco":
            df, meta = fallback()
            meta["warnings"] = [f"基础版无新闻能力（ProMax 专属）"]
            return self._attach(df, meta)

        try:
            df, meta = self._route(produce_pm, produce_major,
                                   dh_name="promax/news",
                                   pm_name="promax/major_news")
        except DataSourceError as exc:
            df, meta = fallback()
            meta["warnings"] = [f"新闻获取失败: {exc.message}"]
        return self._attach(df, meta)

    def _stock_name_of(self, ts: str) -> str:
        df = self.get_stock_list()
        hit = df[df["code"] == code_from_ts(ts)] if not df.empty else df
        return str(hit.iloc[0]["name"]) if not hit.empty else ts

    # ------------------------------------------------------------------
    # 13. get_index_data
    # ------------------------------------------------------------------

    def get_index_data(self, index_code: str = "000001", period: str = "daily",
                       start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        """指数行情（amount 元、volume 股；日/周/月由日线本地聚合）。"""
        if period not in ("daily", "weekly", "monthly"):
            raise DataSourceParamError(f"不支持的 period: {period}")
        ts, name = INDEX_TS_MAP.get(index_code, (None, index_code))
        if ts is None:
            ts = ts_code_of(index_code, asset="index")
        as_of = self._as_of()
        end = iso_to_yyyymmdd(end_date) or as_of
        start = iso_to_yyyymmdd(start_date) or self._shift(end, DEFAULT_LOOKBACK_DAYS)

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.index_daily(ts, start_date=start, end_date=end)
            df = index_df(self._df(fetch))
            df = resample_period(df, period)
            return df, self._meta(fetch, "index_daily",
                                  trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                                  coverage=len(df), warnings=["指数 volume 单位为股（校准）"])

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.index_daily(ts, start_date=start, end_date=end)
            df = index_df(self._df(fetch))
            df = resample_period(df, period)
            return df, self._meta(fetch, "index_daily",
                                  trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                                  coverage=len(df), warnings=["指数 volume 单位为股（校准）"])

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "kline", None,
                cache_key(self.mode, "get_index_data",
                          {"ts": ts, "period": period, "start": start, "end": end}),
                settings.CACHE_TTL_KLINE,
                lambda: self._mock.index_data(index_code, period))
            return self._attach(df, meta)

        df, meta, _ = run_cached(
            self.mode, "kline", None,
            cache_key(self.mode, "get_index_data",
                      {"ts": ts, "period": period, "start": start, "end": end}),
            settings.CACHE_TTL_KLINE,
            lambda: self._route(produce_dh, produce_pm))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 14. get_industry_board_list（可选能力）
    # ------------------------------------------------------------------

    def get_industry_board_list(self) -> pd.DataFrame:
        as_of = self._as_of()

        def produce():
            classify = self._route(
                lambda: self._df(self._dh.index_classify("SW2021", "L1")),
                lambda: self._df(self._pm.index_classify("SW2021", "L1")))
            sw = self._sw_latest_by_code(as_of)
            leading: dict[str, dict] = {}
            try:
                leading = self._leading_by_industry(self._daily_by_date(as_of))
            except DataSourceError as exc:
                logger.warning("领涨股派生跳过（全市场行情不可用）: %s", exc.message)
            df = board_list_df(classify, sw, leading)
            meta = {"source": self.primary, "api": "index_classify+sw_daily",
                    "as_of": as_of, "trade_date": as_of, "fetched_at": time.time(),
                    "is_stale": False, "coverage": len(df), "warnings": [],
                    "leading_count": len(leading)}
            return df, meta

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "boards", None,
                cache_key(self.mode, "get_industry_board_list", {"as_of": as_of}),
                settings.CACHE_TTL_DAILY, lambda: self._mock.board_list())
            return self._attach(df, meta)

        def fallback():
            df = pd.DataFrame(columns=BOARD_COLUMNS)
            return df, {"source": "unavailable", "api": "index_classify+sw_daily",
                        "as_of": as_of, "is_stale": False,
                        "warnings": ["行业板块列表暂不可用"]}

        df, meta, _ = run_cached(
            self.mode, "boards", None,
            cache_key(self.mode, "get_industry_board_list", {"as_of": as_of}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route_optional(produce, None, fallback))
        return self._attach(df, meta)

    def _sw_latest_by_code(self, trade_date: str) -> dict[str, dict] | None:
        """当日全部申万行业行情（sw_daily trade_date 单查），1 天缓存。"""

        def produce():
            fetch = self._pm.sw_daily(trade_date=trade_date)
            raw = self._df(fetch)
            mapping = {str(r["ts_code"]): r for r in raw.to_dict(orient="records")}
            return mapping, self._meta(fetch, "sw_daily", trade_date=trade_date,
                                       coverage=len(mapping))

        try:
            mapping, meta, _ = run_cached(
                self.mode, "boards", None,
                cache_key(self.mode, "sw_daily_by_date", {"as_of": trade_date}),
                settings.CACHE_TTL_DAILY, produce)
            return mapping if isinstance(mapping, dict) else None
        except DataSourceError:
            return None

    def _daily_by_date(self, trade_date: str) -> pd.DataFrame:
        """全市场日线单日（分页 2×5000、去重）——领涨股/涨跌统计/行业估值共用。"""

        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.daily(trade_date=trade_date, paginate=True)
            raw = self._df(fetch)
            dup = int(raw["ts_code"].duplicated().sum())
            raw = raw.drop_duplicates("ts_code")
            meta = self._meta(fetch, "daily", trade_date=trade_date, coverage=len(raw),
                              warnings=(fetch.warnings or []) +
                              ([f"重复代码 {dup} 行已去重"] if dup else []))
            return raw, meta

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.daily(trade_date=trade_date, paginate=True)
            raw = self._df(fetch).drop_duplicates("ts_code")
            return raw, self._meta(fetch, "daily", trade_date=trade_date,
                                   coverage=len(raw), warnings=fetch.warnings or [])

        raw, meta, _ = run_cached(
            self.mode, "boards", None,
            cache_key(self.mode, "daily_by_date", {"as_of": trade_date}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route(produce_dh, produce_pm))
        raw.attrs["data_meta"] = meta
        return raw

    def _leading_by_industry(self, daily: pd.DataFrame) -> dict[str, dict]:
        """行业领涨股 = 成分股当日涨幅最高（覆盖率随 members 覆盖）。"""
        if daily.empty or "pct_chg" not in daily.columns:
            return {}
        members = self._membership_records()
        if members.empty:
            return {}
        merged = daily.merge(members, on="ts_code", how="inner").dropna(subset=["pct_chg"])
        if merged.empty:
            return {}
        top = merged.sort_values("pct_chg", ascending=False).groupby("l1_code").head(1)
        out: dict[str, dict] = {}
        for row in top.to_dict(orient="records"):
            out[str(row["l1_code"])] = {
                "name": row.get("name_x") or row.get("name_y"),
                "pct_change": round(float(row["pct_chg"]), 2)}
        return out

    def _membership_records(self) -> pd.DataFrame:
        mapping = self._industry_membership()
        if not mapping:
            return pd.DataFrame(columns=["ts_code", "l1_code", "l1_name"])
        return pd.DataFrame([{"ts_code": ts, **v} for ts, v in mapping.items()],
                            columns=["ts_code", "l1_code", "l1_name"])

    # ------------------------------------------------------------------
    # 15. get_industry_board_hist（可选能力）
    # ------------------------------------------------------------------

    def get_industry_board_hist(self, name: str, period: str = "daily") -> pd.DataFrame:
        if period not in ("daily", "weekly", "monthly"):
            raise DataSourceParamError(f"不支持的 period: {period}")
        as_of = self._as_of()
        end = as_of
        start = self._shift(end, DEFAULT_LOOKBACK_DAYS)

        def produce():
            code = self._resolve_industry_code(name)
            fetch = self._pm.sw_daily(ts_code=code, start_date=start, end_date=end)
            df = self._sw_hist_contract(self._df(fetch))
            df = resample_period(df, period)
            meta = self._meta(fetch, "sw_daily",
                              trade_date=str(df["date"].iloc[-1]) if len(df) else None,
                              coverage=len(df),
                              warnings=["申万 vol 单位无法解释，保留原值（验收记录）"])
            return df, meta

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "kline", None,
                cache_key(self.mode, "get_industry_board_hist",
                          {"name": name, "period": period, "start": start, "end": end}),
                settings.CACHE_TTL_KLINE,
                lambda: self._mock_industry_hist(name, period))
            return self._attach(df, meta)

        def fallback():
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"]), \
                {"source": "unavailable", "api": "sw_daily", "as_of": as_of,
                 "is_stale": False, "warnings": ["行业历史行情暂不可用"]}

        df, meta, _ = run_cached(
            self.mode, "kline", None,
            cache_key(self.mode, "get_industry_board_hist",
                      {"name": name, "period": period, "start": start, "end": end}),
            settings.CACHE_TTL_KLINE,
            lambda: self._route_optional(produce, None, fallback))
        return self._attach(df, meta)

    def _resolve_industry_code(self, name: str) -> str:
        classify = self._classify_any()
        hit = classify[classify["industry_name"].astype(str) == name] if not classify.empty else classify
        if hit.empty:
            raise DataSourceParamError(f"未找到申万一级行业: {name}", provider=self.primary)
        return str(hit.iloc[0]["index_code"])

    def _classify_any(self) -> pd.DataFrame:
        try:
            return self._df(self._dh.index_classify("SW2021", "L1"))
        except DataSourceError:
            return self._df(self._pm.index_classify("SW2021", "L1"))

    @staticmethod
    def _sw_hist_contract(raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
        return pd.DataFrame({
            "date": raw["trade_date"].map(yyyymmdd_to_iso),
            "open": raw["open"].map(num), "close": raw["close"].map(num),
            "high": raw["high"].map(num), "low": raw["low"].map(num),
            "volume": raw["vol"],
        }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    def _mock_industry_hist(self, name: str, period: str):
        df, meta = self._mock.index_data(name[:6], "daily")
        return df, {**meta, "api": "sw_daily", "warnings": ["模拟行业行情"]}

    # ------------------------------------------------------------------
    # 16. get_market_fund_flow（可选能力；ProMax 专用，逐交易日查询）
    # ------------------------------------------------------------------

    def get_market_fund_flow(self) -> pd.DataFrame:
        as_of = self._as_of()

        def produce():
            days_all = [d for d in self._trade_days(45) if d <= as_of]
            if not days_all:
                return pd.DataFrame(columns=FUND_FLOW_COLUMNS), {
                    "source": "promax", "api": "moneyflow_mkt_dc", "as_of": as_of,
                    "fetched_at": time.time(), "is_stale": False, "coverage": 0,
                    "warnings": ["无已完成交易日"]}
            start = days_all[-30] if len(days_all) >= 30 else days_all[0]
            # 优先区间查询（1 次请求）；不支持区间再逐日循环（30 次小请求）
            try:
                fetch = self._pm.moneyflow_mkt_dc_range(start, as_of)
                raw = self._df(fetch)
                mode = "range"
            except (DataSourceError, AttributeError):
                days = days_all[-30:]
                frames = []
                for d in days:
                    try:
                        frames.append(self._df(self._pm.moneyflow_mkt_dc(trade_date=d)))
                    except DataSourceError:
                        continue
                raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                mode = "per_day"
            df = mkt_fund_flow_df(raw)
            meta = {"source": "promax", "api": "moneyflow_mkt_dc", "as_of": as_of,
                    "trade_date": str(df["date"].iloc[-1]) if len(df) else None,
                    "fetched_at": time.time(), "is_stale": False, "coverage": len(df),
                    "requests": 1 if mode == "range" else 30, "query_mode": mode,
                    "warnings": (["上游区间查询不可用，已逐日查询"] if mode == "per_day" else [])}
            return df, meta

        if self.mode == "mock":
            df, meta = self._run_mock_cached(
                "boards", None,
                cache_key(self.mode, "get_market_fund_flow", {"as_of": as_of}),
                settings.CACHE_TTL_KLINE, lambda: self._mock.market_fund_flow())
            return self._attach(df, meta)
        if self.mode == "datahubco":
            df = pd.DataFrame(columns=FUND_FLOW_COLUMNS)
            return self._attach(df, {
                "source": "unavailable", "api": "moneyflow_mkt_dc", "as_of": as_of,
                "is_stale": False,
                "warnings": ["基础版无大盘资金流能力（ProMax 专用，验收记录: unavailable）"]})

        def fallback():
            return pd.DataFrame(columns=FUND_FLOW_COLUMNS), {
                "source": "unavailable", "api": "moneyflow_mkt_dc", "as_of": as_of,
                "is_stale": False, "warnings": ["大盘资金流暂不可用"]}

        df, meta, _ = run_cached(
            self.mode, "boards", None,
            cache_key(self.mode, "get_market_fund_flow", {"as_of": as_of}),
            settings.CACHE_TTL_KLINE,
            lambda: self._route_optional(produce, None, fallback))
        return self._attach(df, meta)

    # ------------------------------------------------------------------
    # 17. get_industry_pe_pb（可选能力）
    # ------------------------------------------------------------------

    def get_industry_pe_pb(self, industry: str) -> dict:
        as_of = self._as_of()

        def produce():
            code = self._resolve_industry_code(industry)
            fetch = self._pm.index_member_all(l1_code=code, is_new="Y")
            raw = self._df(fetch)
            members = pd.DataFrame({"ts_code": raw["ts_code"].astype(str)}) if not raw.empty \
                else pd.DataFrame(columns=["ts_code"])
            stats = industry_pe_pb_dict(members, self._daily_basic_by_date(as_of))
            meta = {"source": "promax+" + self.primary,
                    "api": "index_member_all+daily_basic", "as_of": as_of,
                    "trade_date": as_of, "fetched_at": time.time(), "is_stale": False,
                    "warnings": ([stats["warning"]] if stats.get("warning") else [])}
            return stats, meta

        if self.mode == "mock":
            stats, meta = self._run_mock_cached(
                "boards", None,
                cache_key(self.mode, "get_industry_pe_pb", {"industry": industry, "as_of": as_of}),
                settings.CACHE_TTL_DAILY, lambda: self._mock.industry_pe_pb(industry))
            return self._attach(stats, meta)
        if self.mode == "datahubco":
            stats = {"pe_median": None, "pb_median": None, "pe_mean": None,
                     "pb_mean": None, "stock_count": 0,
                     "warning": "基础版无申万成分能力（ProMax 专用）"}
            return self._attach(stats, {
                "source": "unavailable", "api": "index_member_all", "as_of": as_of,
                "is_stale": False, "warnings": ["行业估值对比需要 ProMax 申万成分数据"]})

        def fallback():
            return {"pe_median": None, "pb_median": None, "pe_mean": None,
                    "pb_mean": None, "stock_count": 0}, {
                "source": "unavailable", "api": "index_member_all+daily_basic",
                "as_of": as_of, "is_stale": False, "warnings": ["行业估值对比暂不可用"]}

        stats, meta, _ = run_cached(
            self.mode, "boards", None,
            cache_key(self.mode, "get_industry_pe_pb", {"industry": industry, "as_of": as_of}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route_optional(produce, None, fallback))
        return self._attach(stats, meta)

    def _daily_basic_by_date(self, trade_date: str) -> pd.DataFrame:
        def produce_dh():
            self._check_source("datahubco")
            fetch = self._dh.daily_basic(trade_date=trade_date, paginate=True)
            raw = self._df(fetch).drop_duplicates("ts_code")
            return raw, self._meta(fetch, "daily_basic", trade_date=trade_date,
                                   coverage=len(raw))

        def produce_pm():
            self._check_source("promax")
            fetch = self._pm.daily_basic(trade_date=trade_date, paginate=True)
            raw = self._df(fetch).drop_duplicates("ts_code")
            return raw, self._meta(fetch, "daily_basic", trade_date=trade_date,
                                   coverage=len(raw))

        raw, meta, _ = run_cached(
            self.mode, "boards", None,
            cache_key(self.mode, "daily_basic_by_date", {"as_of": trade_date}),
            settings.CACHE_TTL_DAILY,
            lambda: self._route(produce_dh, produce_pm))
        raw.attrs["data_meta"] = meta
        return raw

    # ------------------------------------------------------------------
    # 内部 helper（阶段7 预留: 全市场 daily + stk_limit）
    # ------------------------------------------------------------------

    def daily_with_limits(self, trade_date: str) -> pd.DataFrame:
        """全市场日线 + 涨跌停价（阶段7 涨跌统计用；非 17 契约方法）。

        涨跌判断按 stk_limit 的 up_limit/down_limit 价格比较，不硬编码 10%。
        """
        daily = self._daily_by_date(trade_date)

        def produce_dh():
            return self._df(self._dh.stk_limit(trade_date)), None

        def produce_pm():
            fetch = self._pm.get_rows(
                "stk_limit",
                {"trade_date": trade_date,
                 "fields": "trade_date,ts_code,pre_close,up_limit,down_limit"})
            return self._df(fetch), self._meta(fetch, "stk_limit", trade_date=trade_date)

        try:
            limits_raw, _ = self._route(produce_dh, produce_pm)
        except DataSourceError:
            limits_raw = pd.DataFrame(columns=["ts_code", "up_limit", "down_limit"])
        if limits_raw.empty:
            daily.attrs["data_meta"] = {**(daily.attrs.get("data_meta") or {}),
                                        "warnings": ["涨跌停价缺失"]}
            return daily
        limits = limits_raw[["ts_code", "up_limit", "down_limit"]].drop_duplicates("ts_code")
        out = daily.merge(limits, on="ts_code", how="left")
        out.attrs["data_meta"] = daily.attrs.get("data_meta", {})
        return out

    # ------------------------------------------------------------------
    # 数据源状态（/api/config/data-source-status；不回显密钥、不现场探测）
    # ------------------------------------------------------------------

    def data_source_status(self) -> dict:
        base = settings.data_source_config_status()
        base["providers"]["datahubco"]["config_problems"] = self._dh.config_problems()
        base["providers"]["promax"]["config_problems"] = self._pm.config_problems()
        base["capability_validation"] = None
        status_file = settings.DATA_DIR / "data_source_status.json"
        if status_file.is_file():
            try:
                base["capability_validation"] = json.loads(
                    status_file.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                base["capability_validation"] = None
        return base


def _mock_trade_days(n_back: int) -> list[date]:
    out: list[date] = []
    d = date.today()
    while len(out) < n_back:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _missing_fields(mapping: dict, raw: pd.DataFrame) -> list[str]:
    if raw.empty:
        return []
    return [f"缺字段 {dst}" for src, dst in mapping.items() if src not in raw.columns]
