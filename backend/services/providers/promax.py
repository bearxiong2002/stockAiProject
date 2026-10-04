"""ProMax Relay 数据源（design.md §4.1.3）。

- 业务地址: https://pcd.mobcvb.cn/tushare/pro/{api}（HTTPS，默认校验证书）
- 能力目录: /tushare/capabilities（不在 /tushare/pro 下），含 enabled/required/
  required_any/methods；目录结果内存缓存 1 小时
- 探测与正式请求分离: 正式请求必须带业务筛选；无筛选接口显式 __probe=0；
  limit/offset/fields 不视为业务筛选
- 限流: 普通 Key 2000次/分、IP 200次/分 → 客户端保守 120次/分 + 并发信号量
"""
from __future__ import annotations

import time

import httpx

from config import settings
from services.providers.baseclient import RANGE_CHUNK_DAYS, FetchResult, SourceClient
from services.providers.datahubco import (
    BALANCE_FIELDS,
    CASHFLOW_FIELDS,
    FINA_FIELDS,
    MONEYFLOW_FIELDS,
)

# 不属于业务筛选的参数（仅这些参数时普通 GET 会被识别为探测）
_NON_FILTER_KEYS = {"limit", "offset", "fields", "__probe"}

# 客户端内存缓存的能力目录: api -> capability dict（1 小时）
_CAP_TTL = 3600.0
_caps_cache: dict[str, tuple[float, dict]] = {}


class ProMaxSource(SourceClient):
    provider = "promax"
    read_timeout_attr = "PROMAX_READ_TIMEOUT"
    min_interval = 60.0 / max(1, settings.PROMAX_REQUESTS_PER_MINUTE)  # 120次/分保守预算

    def base_url(self) -> str:
        return settings.PROMAX_BASE_URL

    def api_key(self) -> str:
        return settings.PROMAX_API_KEY

    # -- 能力目录 -----------------------------------------------------------

    def capabilities_catalog(self, *, deadline=None) -> dict:
        """GET /tushare/capabilities（服务根地址，不在 /tushare/pro 下）。

        与 get_rows 同一入口约束：并发信号量 + 限流器（避免高并发下多次
        ensure_enabled 并发击穿 ProMax 配额），错误经 _parse_error 分类。
        """
        import httpx
        import uuid

        started = time.monotonic()
        request_id = uuid.uuid4().hex[:16]
        with self._semaphore:
            self._limiter.wait()
            try:
                resp = self._client.get(
                    "/tushare/capabilities",
                    headers={"X-API-Key": self.api_key(),
                             "X-Request-Id": request_id})
            except httpx.TimeoutException as exc:
                from services.providers.errors import DataSourceTimeoutError
                raise DataSourceTimeoutError(
                    "能力目录请求超时", provider=self.provider, api="capabilities",
                    request_id=request_id, retryable=True) from exc
            except httpx.HTTPError as exc:
                from services.providers.errors import DataSourceProtocolError
                raise DataSourceProtocolError(
                    f"网络错误: {type(exc).__name__}", provider=self.provider,
                    api="capabilities", request_id=request_id) from exc
        if resp.status_code != 200:
            raise self._parse_error(resp, request_id)
        try:
            body = resp.json()
        except ValueError as exc:
            from services.providers.errors import DataSourceProtocolError
            raise DataSourceProtocolError(
                "能力目录响应非 JSON", provider=self.provider,
                api="capabilities", request_id=request_id) from exc
        self._probe_elapsed_ms = round((time.monotonic() - started) * 1000)
        return {it.get("name"): it for it in (body.get("interfaces") or [])}

    def capability(self, api: str, *, refresh: bool = False) -> dict | None:
        """单项能力（内存缓存 1h）。enabled=False 的接口直接 unavailable。"""
        now = time.time()
        if not refresh:
            cached = _caps_cache.get(api)
            if cached and now - cached[0] < _CAP_TTL:
                return cached[1]
        catalog = self.capabilities_catalog()
        cap = catalog.get(api)
        if cap is not None:
            _caps_cache[api] = (now, cap)
        return cap

    def ensure_enabled(self, api: str, *, refresh: bool = False) -> dict:
        cap = self.capability(api, refresh=refresh)
        if cap is None:
            from services.providers.errors import DataSourceUnavailableError
            raise DataSourceUnavailableError(
                f"ProMax 能力目录中不存在接口 {api}", provider=self.provider, api=api)
        if not cap.get("enabled", False):
            from services.providers.errors import DataSourceUnavailableError
            raise DataSourceUnavailableError(
                f"ProMax 接口未启用: {api}", provider=self.provider, api=api)
        return cap

    def formal_params(self, api: str, params: dict) -> dict:
        """补齐正式请求保护: 无业务筛选时显式 __probe=0（探测不入业务路径）。"""
        out = dict(params)
        business = [k for k in out if k not in _NON_FILTER_KEYS and k != "__probe"]
        if not business and "__probe" not in out:
            out["__probe"] = 0
        return out

    # -- 行情 ---------------------------------------------------------------

    def daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None,
              *, paginate: bool = False, deadline=None) -> FetchResult:
        params: dict = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date and end_date:
            params["start_date"], params["end_date"] = start_date, end_date
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        params = self.formal_params("daily", params)
        if paginate:
            return self.fetch_all("daily", params, fields=fields, deadline=deadline)
        return self.get_rows("daily", {**params, "fields": fields}, deadline=deadline)

    def daily_basic(self, ts_code=None, trade_date=None, start_date=None, end_date=None,
                    *, paginate: bool = False, deadline=None) -> FetchResult:
        params: dict = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date and end_date:
            params["start_date"], params["end_date"] = start_date, end_date
        fields = ("ts_code,trade_date,close,turnover_rate,volume_ratio,"
                  "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_mv,circ_mv,"
                  "total_share,float_share")
        params = self.formal_params("daily_basic", params)
        if paginate:
            return self.fetch_all("daily_basic", params, fields=fields, deadline=deadline)
        return self.get_rows("daily_basic", {**params, "fields": fields}, deadline=deadline)

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> FetchResult:
        params = self.formal_params("adj_factor", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date})
        return self.get_rows("adj_factor", {
            **params, "fields": "ts_code,trade_date,adj_factor"})

    def pro_bar(self, ts_code: str, *, freq: str = "D", asset: str = "E", adj: str | None,
                start_date: str, end_date: str) -> FetchResult:
        params = self.formal_params("pro_bar", {
            "ts_code": ts_code, "freq": freq, "asset": asset,
            "start_date": start_date, "end_date": end_date})
        if adj:
            params["adj"] = adj
        return self.get_rows("pro_bar", params)

    def index_daily(self, ts_code: str, trade_date=None, start_date=None, end_date=None) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if trade_date:
            params["trade_date"] = trade_date
        if start_date and end_date:
            params["start_date"], params["end_date"] = start_date, end_date
        params = self.formal_params("index_daily", params)
        if (start_date and end_date
                and self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS):
            return self.fetch_date_chunks(
                "index_daily", params, start_date, end_date,
                fields="ts_code,trade_date,open,high,low,close,vol,amount")
        return self.get_rows("index_daily", {
            **params, "fields": "ts_code,trade_date,open,high,low,close,vol,amount"})

    def trade_cal(self, start_date: str, end_date: str) -> FetchResult:
        params = self.formal_params("trade_cal", {
            "exchange": "SSE", "start_date": start_date, "end_date": end_date})
        return self.get_rows("trade_cal", {
            **params, "fields": "exchange,cal_date,is_open,pretrade_date"})

    def stock_basic_row(self, ts_code: str, *, list_status: str = "L") -> FetchResult:
        params = self.formal_params("stock_basic", {
            "ts_code": ts_code, "list_status": list_status})
        return self.get_rows("stock_basic", {**params,
                                             "fields": "ts_code,symbol,name,area,industry,market,list_date"})

    def stock_list_page(self, *, list_status: str = "L", page_size: int = 5000,
                        offset: int = 0, paginate: bool = False, deadline=None) -> FetchResult:
        params = {"list_status": list_status}
        fields = "ts_code,symbol,name,area,industry,cnspell,market,list_date"
        if paginate:
            return self.fetch_all("stock_basic", {**params, "fields": fields},
                                  page_size=page_size, deadline=deadline)
        return self.get_rows("stock_basic",
                             {**params, "limit": page_size, "offset": offset,
                              "fields": fields},
                             deadline=deadline)

    # -- 财务 ---------------------------------------------------------------

    def fina_indicator(self, ts_code: str, period=None) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if period:
            params["period"] = period
        return self.get_rows("fina_indicator", {
            **self.formal_params("fina_indicator", params), "fields": FINA_FIELDS})

    def income(self, ts_code: str, period=None) -> FetchResult:
        return self._fin("income", ts_code, period, INCOME_FIELDS)

    def balancesheet(self, ts_code: str, period=None) -> FetchResult:
        return self._fin("balancesheet", ts_code, period, BALANCE_FIELDS)

    def cashflow(self, ts_code: str, period=None) -> FetchResult:
        return self._fin("cashflow", ts_code, period, CASHFLOW_FIELDS)

    def _fin(self, api: str, ts_code: str, period, fields: str) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if period:
            params["period"] = period
        return self.get_rows(api, {**self.formal_params(api, params), "fields": fields})

    def dividend(self, ts_code: str) -> FetchResult:
        params = self.formal_params("dividend", {"ts_code": ts_code})
        return self.get_rows("dividend", {
            **params,
            "fields": "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date"})

    # -- 股东 ---------------------------------------------------------------

    def top10_holders(self, ts_code: str) -> FetchResult:
        # limit=10: 不传 limit 时上游返回历史首段（旧期）而非最新报告期
        params = self.formal_params("top10_holders", {"ts_code": ts_code, "limit": 10})
        return self.get_rows("top10_holders", {
            **params,
            "fields": "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio,hold_float_ratio,hold_change,holder_type"})

    # -- 资金 ---------------------------------------------------------------

    def moneyflow(self, ts_code: str, start_date: str, end_date: str) -> FetchResult:
        params = self.formal_params("moneyflow", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date})
        return self.get_rows("moneyflow", {**params, "fields": MONEYFLOW_FIELDS})

    def moneyflow_mkt_dc(self, trade_date: str) -> FetchResult:
        params = self.formal_params("moneyflow_mkt_dc", {"trade_date": trade_date})
        return self.get_rows("moneyflow_mkt_dc", {
            **params,
            "fields": "trade_date,close_sh,pct_change_sh,close_sz,pct_change_sz,net_amount,net_amount_rate,buy_elg_amount,buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate"})

    def moneyflow_mkt_dc_range(self, start_date: str, end_date: str) -> FetchResult:
        """区间尝试（官方 moneyflow_mkt_dc 仅 trade_date；支持则 1 次请求）。

        上游返回 invalid_params 时上层回退到逐日查询。
        """
        params = {"start_date": start_date, "end_date": end_date}
        params = self.formal_params("moneyflow_mkt_dc", params)
        return self.get_rows("moneyflow_mkt_dc", {
            **params,
            "fields": "trade_date,close_sh,pct_change_sh,close_sz,pct_change_sz,net_amount,net_amount_rate,buy_elg_amount,buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate"})

    # -- 筹码分布 ---------------------------------------------------------------

    def cyq_chips(self, ts_code: str, trade_date: str) -> FetchResult:
        params = self.formal_params("cyq_chips", {
            "ts_code": ts_code, "trade_date": trade_date})
        return self.get_rows("cyq_chips", {**params, "fields": "ts_code,trade_date,price,percent"})

    def cyq_perf(self, ts_code: str, trade_date: str) -> FetchResult:
        params = self.formal_params("cyq_perf", {
            "ts_code": ts_code, "trade_date": trade_date})
        return self.get_rows("cyq_perf", {
            **params,
            "fields": "ts_code,trade_date,his_low,his_high,cost_5pct,cost_15pct,cost_25pct,cost_75pct,cost_85pct,cost_95pct,weight_avg,winner_rate"})

    # -- 申万行业 / 新闻 -----------------------------------------------------

    def sw_daily(self, ts_code: str | None = None, trade_date: str | None = None,
                 start_date: str | None = None, end_date: str | None = None) -> FetchResult:
        params: dict = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date and end_date:
            params["start_date"], params["end_date"] = start_date, end_date
        params = self.formal_params("sw_daily", params)
        fields = ("ts_code,trade_date,open,high,low,close,vol,amount,"
                  "pct_change,change,name,pe,pb,float_mv,total_mv")
        if (start_date and end_date
                and self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS):
            return self.fetch_date_chunks("sw_daily", params, start_date, end_date,
                                          fields=fields)
        return self.get_rows("sw_daily", {**params, "fields": fields})

    def index_classify(self, src: str = "SW2021", level: str | None = "L1") -> FetchResult:
        params: dict = {"src": src}
        if level:
            params["level"] = level
        return self.get_rows("index_classify", {
            **params, "fields": "index_code,industry_name,parent_code,level,industry_code,is_pub"})

    def index_member_all(self, l1_code: str | None = None, ts_code: str | None = None,
                         is_new: str = "Y", *, paginate: bool = False, deadline=None) -> FetchResult:
        params: dict = {"is_new": is_new}
        if l1_code:
            params["l1_code"] = l1_code
        if ts_code:
            params["ts_code"] = ts_code
        fields = ("l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,"
                  "ts_code,name,in_date,out_date")
        params = self.formal_params("index_member_all", params)
        if paginate:
            return self.fetch_all("index_member_all", params, fields=fields, deadline=deadline)
        return self.get_rows("index_member_all", {**params, "fields": fields}, deadline=deadline)

    def news(self, src: str, start_date: str, end_date: str, limit: int = 200) -> FetchResult:
        params = {"src": src, "start_date": start_date, "end_date": end_date, "limit": limit}
        return self.get_rows("news", params)

    def major_news(self, src: str, start_date: str, end_date: str, limit: int = 200) -> FetchResult:
        params = {"src": src, "start_date": start_date, "end_date": end_date, "limit": limit}
        return self.get_rows("major_news", params)
