"""Datahubco 基础版数据源（design.md §4.1.3）。

- 业务地址: http://datahubco.com/app-api/openapi/v1/tushare（手册 §2: 当前仅 HTTP）
- 鉴权: X-API-Key 请求头（settings.DATAHUBCO_API_KEY，绝不入 URL/日志）
- 规范接口名 stock_basic（手册名，已真实验收）；用户示例别名 stock-basic 已单独验证，
  记录在验收文档，不作为生产路径。
- 手册 §9 已验收本地接口族: daily/daily_basic/adj_factor/index_daily/index_dailybasic/
  stock_basic/trade_cal（+本次验证的财务/资金/涨跌停/申万等上游路由）
"""
from __future__ import annotations

import httpx

from config import settings
from services.providers.baseclient import RANGE_CHUNK_DAYS, FetchResult, SourceClient


class DatahubcoSource(SourceClient):
    provider = "datahubco"
    read_timeout_attr = "DATAHUBCO_READ_TIMEOUT"

    # 规范名映射: 能力名 -> 供应商路径（都经正式业务验证后才可进入）
    STOCK_LIST_API = "stock_basic"   # 用户示例别名 stock-basic 同样可用（验收记录单列）

    def base_url(self) -> str:
        return settings.DATAHUBCO_BASE_URL

    def api_key(self) -> str:
        return settings.DATAHUBCO_API_KEY

    def http_needs_explicit_allow(self) -> bool:
        return True  # 明文 HTTP 需显式允许

    # -- 基础资料 -----------------------------------------------------------

    def stock_list_page(self, *, list_status: str = "L", page_size: int = 5000,
                        offset: int = 0, paginate: bool = False, deadline=None):
        params = {"list_status": list_status}
        fields = ("ts_code,symbol,name,area,industry,cnspell,market,list_date")
        if paginate:
            return self.fetch_all(self.STOCK_LIST_API,
                                  {**params, "fields": fields},
                                  page_size=page_size, deadline=deadline)
        return self.get_rows(self.STOCK_LIST_API,
                             {**params, "limit": page_size, "offset": offset,
                              "fields": fields},
                             deadline=deadline)

    def stock_basic_row(self, ts_code: str, *, list_status: str = "L") -> FetchResult:
        return self.get_rows(self.STOCK_LIST_API,
                             {"ts_code": ts_code, "list_status": list_status},
                             deadline=None)

    def trade_cal(self, start_date: str, end_date: str) -> FetchResult:
        return self.get_rows("trade_cal", {
            "exchange": "SSE", "start_date": start_date, "end_date": end_date,
            "fields": "exchange,cal_date,is_open,pretrade_date"})

    # -- 行情 ---------------------------------------------------------------

    def daily(self, ts_code: str | None = None, trade_date: str | None = None,
              start_date: str | None = None, end_date: str | None = None,
              *, paginate: bool = False, deadline=None) -> FetchResult:
        params: dict = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date and end_date:
            params["start_date"], params["end_date"] = start_date, end_date
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        if paginate:
            # trade_date 全市场（约 5550 行，2 页）与区间形状统一分页
            return self.fetch_all("daily", params, fields=fields, deadline=deadline)
        if trade_date:
            return self.get_rows("daily", {**params, "fields": fields}, deadline=deadline)
        if start_date and end_date and self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS:
            return self.fetch_date_chunks("daily", params, start_date, end_date,
                                          fields=fields, deadline=deadline)
        return self.get_rows("daily", {**params, "fields": fields}, deadline=deadline)

    def daily_basic(self, ts_code: str | None = None, trade_date: str | None = None,
                    start_date: str | None = None, end_date: str | None = None,
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
        if trade_date:
            if paginate:
                return self.fetch_all("daily_basic", params, fields=fields, deadline=deadline)
            return self.get_rows("daily_basic", {**params, "fields": fields}, deadline=deadline)
        if paginate:
            return self.fetch_all("daily_basic", params, fields=fields, deadline=deadline)
        if start_date and end_date and self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS:
            return self.fetch_date_chunks("daily_basic", params, start_date, end_date,
                                          fields=fields, deadline=deadline)
        return self.get_rows("daily_basic", {**params, "fields": fields}, deadline=deadline)

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> FetchResult:
        params = {"ts_code": ts_code,
                  "fields": "ts_code,trade_date,adj_factor"}
        if self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS:
            return self.fetch_date_chunks("adj_factor", params, start_date, end_date,
                                          fields=params["fields"])
        return self.get_rows("adj_factor", {
            **params, "start_date": start_date, "end_date": end_date})



    def index_daily(self, ts_code: str, trade_date: str | None = None,
                    start_date: str | None = None, end_date: str | None = None) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if trade_date:
            params["trade_date"] = trade_date
        fields = "ts_code,trade_date,open,high,low,close,vol,amount"
        if trade_date:
            return self.get_rows("index_daily", {**params, "fields": fields})
        if start_date and end_date and self._span_days(start_date, end_date) > RANGE_CHUNK_DAYS:
            return self.fetch_date_chunks("index_daily", params, start_date, end_date,
                                          fields=fields)
        return self.get_rows("index_daily", {**params, "fields": fields})

    # -- 财务 ---------------------------------------------------------------

    def fina_indicator(self, ts_code: str, period: str | None = None) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if period:
            params["period"] = period
        return self.get_rows("fina_indicator", {**params, "fields": FINA_FIELDS})

    def income(self, ts_code: str, period: str | None = None) -> FetchResult:
        return self._fin_statement("income", ts_code, period, INCOME_FIELDS)

    def balancesheet(self, ts_code: str, period: str | None = None) -> FetchResult:
        return self._fin_statement("balancesheet", ts_code, period, BALANCE_FIELDS)

    def cashflow(self, ts_code: str, period: str | None = None) -> FetchResult:
        return self._fin_statement("cashflow", ts_code, period, CASHFLOW_FIELDS)

    def _fin_statement(self, api: str, ts_code: str, period: str | None, fields: str) -> FetchResult:
        params: dict = {"ts_code": ts_code}
        if period:
            params["period"] = period
        return self.get_rows(api, {**params, "fields": fields})

    def dividend(self, ts_code: str) -> FetchResult:
        return self.get_rows("dividend", {
            "ts_code": ts_code,
            "fields": "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date"})

    # -- 资金 / 涨跌停 ------------------------------------------------------

    def moneyflow(self, ts_code: str, start_date: str, end_date: str) -> FetchResult:
        return self.get_rows("moneyflow", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
            "fields": MONEYFLOW_FIELDS})

    def stk_limit(self, trade_date: str) -> FetchResult:
        return self.get_rows("stk_limit", {
            "trade_date": trade_date,
            "fields": "trade_date,ts_code,pre_close,up_limit,down_limit"})

    # -- 申万行业 -----------------------------------------------------------

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
        if paginate:
            return self.fetch_all("index_member_all", params, fields=fields, deadline=deadline)
        return self.get_rows("index_member_all", {**params, "fields": fields}, deadline=deadline)


# 请求字段固定顺序（fields 顺序参与上游缓存键，必须固定）
FINA_FIELDS = ("ts_code,ann_date,end_date,eps,bps,roe,roa,grossprofit_margin,"
               "netprofit_margin,or_yoy,netprofit_yoy,debt_to_assets,current_ratio")
INCOME_FIELDS = ("ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                 "revenue,total_revenue,oper_cost,operate_profit,total_profit,"
                 "income_tax,n_income,n_income_attr_p")
BALANCE_FIELDS = ("ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                  "money_cap,accounts_receiv,inventories,total_cur_assets,"
                  "total_assets,total_liab,total_hldr_eqy_exc_min_int")
CASHFLOW_FIELDS = ("ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                   "n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,"
                   "n_incr_cash_cash_equ,net_profit")
MONEYFLOW_FIELDS = ("ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,"
                    "buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,"
                    "buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,"
                    "buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,"
                    "net_mf_vol,net_mf_amount")

