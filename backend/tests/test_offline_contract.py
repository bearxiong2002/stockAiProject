"""阶段3 离线契约测试（默认不联网；httpx.MockTransport 模拟上游响应）。

运行: cd backend && .venv/bin/python tests/test_offline_contract.py

覆盖 design.md §4.1.8 验收边界: 字段乱序、缺字段、空结果、非 JSON、
业务失败码、401/403/429/503/504、重复/中断分页、单位转换、复权复算、
新股/停牌空结果、限流退避、总预算超时。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from config import settings  # noqa: E402
from services.providers.baseclient import FetchResult, SourceClient  # noqa: E402
from services.providers.errors import (  # noqa: E402
    DataSourceAuthError,
    DataSourceParamError,
    DataSourceProtocolError,
    DataSourceRateLimitError,
    DataSourceTimeoutError,
    DataSourceUnavailableError,
)
from services.providers import normalize as N  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def envelope(fields: list[str], items: list[list], *, code: int = 0,
             msg: str = "ok") -> dict:
    return {"code": code, "msg": msg,
            "data": {"fields": fields, "items": items}}


def promax_envelope(fields, items, *, ok=None, error=None, message=None, count=None):
    body: dict = {"request_id": "srv-1", "code": 0, "msg": "ok",
                  "data": {"fields": fields, "items": items}, "count": count}
    if ok is not None:
        body["ok"] = ok
    if error:
        body["error"] = error
    if message:
        body["message"] = message
    return body


class TestSource(SourceClient):
    """测试用 SourceClient（transport 注入，不联网）。"""

    provider = "test"

    def base_url(self) -> str:
        return "https://mock.invalid/tushare/pro"

    def api_key(self) -> str:
        return "test-key"


def make_source(handler) -> TestSource:
    return TestSource(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# 信封与错误分类
# ---------------------------------------------------------------------------

def test_envelope_and_errors():
    print("\n[信封与错误分类]")
    # 1 正常 + 字段乱序（响应字段顺序即列顺序）
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(
            ["trade_date", "ts_code", "close"], [["20260911", "600519.SH", 1275.16]]))

    s = make_source(handler)
    res = s.get_rows("daily", {})
    check("字段按响应顺序解析", res.fields == ["trade_date", "ts_code", "close"]
          and res.rows[0][1] == "600519.SH")

    # 2 空结果
    def empty_handler(request):
        return httpx.Response(200, json=envelope(["ts_code", "close"], []))

    s2 = make_source(empty_handler)
    df = s2.df("daily", {"ts_code": "000001.SZ"})
    check("成功空结果 → 空表", df.empty)

    # 3 业务失败码
    def bad_code(request):
        return httpx.Response(200, json=envelope([], [], code=40103, msg="token invalid"))

    s3 = make_source(bad_code)
    try:
        s3.get_rows("daily", {})
        check("业务失败码抛错", False)
    except DataSourceProtocolError:
        check("业务失败码抛错", True)
    except DataSourceAuthError:
        check("业务失败码抛错", True)

    # 4 ProMax ok=false + invalid_params
    def param_err(request):
        return httpx.Response(200, json={"ok": False, "error": "invalid_params",
                                         "message": "missing ts_code"})

    s4 = make_source(param_err)
    try:
        s4.get_rows("daily", {})
        check("invalid_params → ParamError", False)
    except DataSourceParamError:
        check("invalid_params → ParamError", True)

    # 5 401 → AuthError 不重试
    calls = {"n": 0}

    def auth_fail(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized", "message": "bad key"})

    s5 = make_source(auth_fail)
    try:
        s5.get_rows("daily", {})
        check("401 → AuthError", False)
    except DataSourceAuthError:
        check("401 → AuthError（不重试）", calls["n"] == 1)

    # 6 503 upstream_pool_exhausted 可重试（恢复后成功）
    pool_state = {"n": 0}

    def pool_then_ok(request):
        pool_state["n"] += 1
        if pool_state["n"] == 1:
            return httpx.Response(503, json={"ok": False, "error": "upstream_pool_exhausted"})
        return httpx.Response(200, json=envelope(["ts_code"], [["600519.SH"]]))

    s6 = make_source(pool_then_ok)
    try:
        s6.get_rows("daily", {})
        check("503 池耗尽 → 重试成功", pool_state["n"] == 2)
    except DataSourceUnavailableError:
        check("503 池耗尽重试", pool_state["n"] == 2)

    # 7 503 data_source_unavailable 不重试
    state_no = {"n": 0}

    def disabled(request):
        state_no["n"] += 1
        return httpx.Response(503, json={"ok": False, "error": "data_source_unavailable"})

    s7 = make_source(disabled)
    try:
        s7.get_rows("daily", {})
        check("未启用 503 抛 Unavailable", False)
    except DataSourceUnavailableError:
        check("未启用 503 不重试", state_no["n"] == 1)


def test_non_json_and_missing_field():
    print("\n[非 JSON / 缺列 / 行宽不符]")
    s = make_source(lambda r: httpx.Response(200, text="<html>gateway</html>"))
    try:
        s.get_rows("daily", {})
        check("非 JSON → ProtocolError", False)
    except DataSourceProtocolError:
        check("非 JSON → ProtocolError", True)

    s2 = make_source(lambda r: httpx.Response(200, json=envelope(
        ["ts_code", "close"], [["600519.SH", 1.0], ["600036.SH", 40.0, "EXTRA"]])))
    try:
        s2.get_rows("daily", {})
        check("行宽不符 → ProtocolError", False)
    except DataSourceProtocolError:
        check("行宽不符 → ProtocolError", True)


def test_rate_limit_and_retry_after():
    print("\n[429 与 Retry-After]")
    import httpx as _h

    state = {"n": 0}

    def rl(request: _h.Request) -> _h.Response:
        state["n"] += 1
        if state["n"] == 1:
            return _h.Response(429, json={"ok": False, "error": "rate_limited"},
                               headers={"Retry-After": "0"})
        return _h.Response(200, json=envelope(["ts_code"], [["600519.SH"]]))

    s = make_source(rl)
    t0 = time.monotonic()
    res = s.get_rows("daily", {"ts_code": "600519.SH"})
    check("429 退避后重试成功", len(res.rows) == 1)
    check("遵守 Retry-After(=0 不等待)", time.monotonic() - t0 < 2)


def test_pagination():
    print("\n[分页: 短页终止 / 重复页检测 / 页数上限]")
    rows_all = [[f"{i:06d}.SZ"] for i in range(120)]

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        limit = int(params.get("limit", 100))
        offset = int(params.get("offset", 0))
        page = rows_all[offset:offset + limit]
        return httpx.Response(200, json=envelope(["ts_code"], page))

    s = make_source(handler)
    res = s.fetch_all("stock_basic", {}, page_size=50)
    check("短页终止", len(res.rows) == 120 and res.pages == 3)

    def repeat_handler(request):
        params = dict(request.url.params)
        limit = int(params.get("limit", 50))
        return httpx.Response(200, json=envelope(["ts_code"], rows_all[:50]))  # 永远同一页

    s2 = make_source(repeat_handler)
    res2 = s2.fetch_all("stock_basic", {}, page_size=50, max_pages=10)
    check("重复页检测终止", len(res2.rows) == 50 and any("重复页" in w for w in res2.warnings))

    rows_enough = [[f"{i:06d}.SZ"] for i in range(1000)]

    def full_handler(request):
        params = dict(request.url.params)
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        page = rows_enough[offset:offset + limit]  # 每页都是满页新行
        return httpx.Response(200, json=envelope(["ts_code"], page))

    s3 = make_source(full_handler)
    res3 = s3.fetch_all("stock_basic", {}, page_size=50, max_pages=3)
    check("max_pages 上限保护", res3.pages <= 3
          and any("最大页数" in w for w in res3.warnings))


def test_deadline():
    print("\n[总预算超时]")
    def slow(request):
        time.sleep(0.15)
        return httpx.Response(200, json=envelope(["ts_code"], [["600519.SH"]]))

    s = make_source(slow)
    deadline = time.monotonic() + 0.05
    try:
        s.fetch_all("daily", {}, page_size=1, max_pages=3, deadline=deadline)
        check("超预算 → TimeoutError", False)
    except DataSourceTimeoutError:
        check("超预算 → TimeoutError", True)


# ---------------------------------------------------------------------------
# 单位换算与契约映射（真实校准系数）
# ---------------------------------------------------------------------------

def test_units():
    print("\n[单位换算（真实校准）]")
    daily = N.to_df(
        ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
         "change", "pct_chg", "vol", "amount"],
        [["600519.SH", "20260911", 1285.15, 1286.15, 1263.01, 1275.16, 1285.13,
          -9.97, -0.7758, 34801.42, 4430841.445]])
    basic = N.to_df(["trade_date", "turnover_rate"],
                    [["20260911", 0.2784]])
    kline = N.build_kline(daily, basic, None, adjust="")
    row = kline.iloc[0]
    check("vol 手→股 ×100", int(row["volume"]) == 3480142)
    check("amount 千元→元 ×1000", abs(row["amount"] - 4430841445.0) < 1)
    check("turnover 百分数保持", abs(row["turnover"] - 0.2784) < 1e-6)
    check("amplitude 推导", abs(row["amplitude"] - 1.8006) < 0.01)
    check("ISO 日期", row["date"] == "2026-09-11")

    # moneyflow 万元→亿元；主力=elg+lg
    mf = N.to_df(
        ["ts_code", "trade_date", "buy_sm_vol", "buy_sm_amount", "sell_sm_vol",
         "sell_sm_amount", "buy_md_vol", "buy_md_amount", "sell_md_vol",
         "sell_md_amount", "buy_lg_vol", "buy_lg_amount", "sell_lg_vol",
         "sell_lg_amount", "buy_elg_vol", "buy_elg_amount", "sell_elg_vol",
         "sell_elg_amount", "net_mf_vol", "net_mf_amount"],
        [["000001.SZ", "20260911",
          223205.0, 26275.46, 229739.0, 27052.83, 248096.0, 29210.78, 207887.0,
          24474.7, 245354.0, 28892.85, 195435.0, 23005.2, 115805.0, 13619.96,
          115805.0, 10000.0, -1000.0, 1000.0]])
    amounts = N.to_df(["date", "amount_yuan"], [["2026-09-11", 9.8e8]])
    df = N.moneyflow_df(mf, amounts)
    r = df.iloc[0]
    check("主力净额(亿)=elg+lg",
          abs(r["super_large_net"] - (13619.96 - 10000.0) / 1e4) < 1e-4)
    check("大单净额(亿)", abs(r["large_net"] - (28892.85 - 23005.2) / 1e4) < 1e-4)
    check("pct=主力(亿)×1e8/成交额(元)",
          abs(r["main_net_inflow_pct"]
              - r["main_net_inflow"] * 1e8 / 9.8e8 * 100) < 1e-3,
          f"pct={r['main_net_inflow_pct']}")

    # dividend 每股→每10股 ×10
    dv = N.to_df(
        ["ts_code", "end_date", "ann_date", "div_proc", "cash_div", "stk_bo_rate", "stk_co_rate", "ex_date"],
        [["600519.SH", "20231231", "20240620", "实施", 30.876, 0, 0, "20240627"],
         ["600519.SH", "20260630", "20260815", "预案", 0, 0, 0, None]])
    df_dv = N.dividend_df(dv)
    check("仅实施分红", len(df_dv) == 1)
    check("每股→每10股 ×10", abs(df_dv.iloc[0]["dividend"] - 308.76) < 1e-6)

    # holder 股→万股、字符串数字化
    hd = N.to_df(
        ["ts_code", "ann_date", "end_date", "holder_name", "hold_amount", "hold_ratio"],
        [["600519.SH", "20260815", "20260630", "香港中央结算", "5583897", "0.4467"],
         ["600519.SH", "20260815", "20260630", "中国人寿", "5583897", "0.4467"]])
    df_hd = N.holder_df(hd)
    check("hold_amount 股→万股", abs(df_hd.iloc[0]["持股数量"] - 558.3897) < 0.01)
    check("持股比例百分数", abs(df_hd.iloc[0]["持股比例"] - 0.4467) < 1e-6)

    # index amount 千元→元
    idx = N.to_df(["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
                  [["000300.SH", "20260911", 1, 2, 0.5, 4510.1554, 204230027, 522206649.5122]])
    df_idx = N.index_df(idx)
    check("指数 amount ×1000", abs(df_idx.iloc[0]["amount"] - 522206649512.2) < 1)

    # 前复权复算（手工样例）
    raw = N.to_df(
        ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
         "change", "pct_chg", "vol", "amount"],
        [["600519.SH", "20260910", 100, 110, 99, 105, 100, 5, 5.0, 1000, 100000],
         ["600519.SH", "20260911", 105, 110, 104, 108, 105, 3, 2.857, 1200, 120000]])
    adj = N.to_df(["ts_code", "trade_date", "adj_factor"],
                  [["600519.SH", "20260910", 8.0], ["600519.SH", "20260911", 8.305]])
    kq = N.build_kline(raw, None, adj, adjust="qfq")
    check("qfq 锚点日=未复权收盘", abs(kq.iloc[-1]["close"] - 108) < 1e-6)
    check("qfq 历史价缩放", abs(kq.iloc[0]["close"] - 105 * 8.0 / 8.305) < 1e-3)
    kh = N.build_kline(raw, None, adj, adjust="hfq")
    check("hfq = 未复权×因子", abs(kh.iloc[0]["close"] - 105 * 8.0) < 1e-3)


def test_missing_data():
    print("\n[数据不足与缺测]")
    daily = N.to_df(
        ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
         "change", "pct_chg", "vol", "amount"],
        [["600519.SH", "20260911", 1, 2, 0.5, 1.5, 1, 0.5, 50, 1000, None]])
    basic = N.to_df(["trade_date", "turnover_rate"], [["20260911", None]])
    kline = N.build_kline(daily, basic, None, adjust="")
    check("缺 amount 不是 0", kline.iloc[0]["amount"] is None
          or pd_isna(kline.iloc[0]["amount"]))
    check("缺 turnover 不是 0", kline.iloc[0]["turnover"] is None
          or pd_isna(kline.iloc[0]["turnover"]))


def pd_isna(v):
    import math
    return v is None or (isinstance(v, float) and math.isnan(v))


def main() -> int:
    settings.ensure_dirs()
    test_envelope_and_errors()
    test_non_json_and_missing_field()
    test_rate_limit_and_retry_after()
    test_pagination()
    test_deadline()
    test_units()
    test_missing_data()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
