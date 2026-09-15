"""阶段3.1 双端真实连通性与权限探测（opt-in，会发起真实网络请求）。

运行: cd backend && .venv/bin/python tests/probe_real_apis.py

- 密钥从 backend/.env / 环境变量读取，绝不打印
- 输出脱敏记录: HTTP 状态、业务码、字段、行数、数据时间、耗时、关键响应头
- 结论分类: 文档声明 / 探测通过 / 正式请求通过 / 目录通过 / 不支持 / 权限不足
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from config import settings  # noqa: E402

RESULTS: list[dict] = []


def _client(base: str, read_timeout: float) -> httpx.Client:
    return httpx.Client(
        base_url=base,
        timeout=httpx.Timeout(connect=settings.STOCK_HTTP_CONNECT_TIMEOUT,
                              read=read_timeout, write=10, pool=read_timeout),
        trust_env=settings.STOCK_HTTP_TRUST_ENV,
        verify=True,
        follow_redirects=False,
    )


def _request(client: httpx.Client, path: str, params: dict, key: str,
             retries: int = 2) -> tuple[httpx.Response, list[float]]:
    """带退避重试的 GET；仅对可恢复错误重试（429/502/503/504/网络错误）。"""
    sleeps: list[float] = []
    attempt = 0
    while True:
        headers = {
            "X-API-Key": key,
            "X-Request-Id": f"stockpanel-probe-{int(time.time() * 1000)}-{attempt}",
        }
        start = time.perf_counter()
        try:
            r = client.get(path, params=params, headers=headers)
            retryable = r.status_code in (429, 502, 503, 504)
        except httpx.HTTPError:
            retryable = True
            r = None  # type: ignore[assignment]
        if not retryable or attempt >= retries:
            return r, sleeps
        wait = min(1.0 * (2 ** attempt) + 0.2, 4.0)
        # 429 优先读 Retry-After
        if r is not None and r.status_code == 429:
            wait = float(r.headers.get("Retry-After", wait) or wait)
        sleeps.append(wait)
        attempt += 1
        time.sleep(wait)


def probe(client: httpx.Client, provider: str, path: str, params: dict, *,
          name: str, kind: str) -> dict:
    """记录一条脱敏探测结果。kind: formal | probe | catalog"""
    key = settings.DATAHUBCO_API_KEY if provider == "datahubco" else settings.PROMAX_API_KEY
    record: dict = {"provider": provider, "name": name, "kind": kind,
                    "url_path": path,
                    "params": {k: v for k, v in params.items() if k != "fields"},
                    "ts": time.strftime("%H:%M:%S")}
    start = time.perf_counter()
    try:
        r, backoffs = _request(client, path, params, key)
        if r is None:
            record.update({"ok": False, "conclusion": "网络错误（重试后仍失败）",
                           "backoffs": backoffs})
        else:
            record["http_status"] = r.status_code
            record["headers"] = {h: r.headers[h] for h in
                                 ("X-Data-Source", "X-Cache", "X-Request-ID",
                                  "Retry-After", "X-RateLimit-Remaining",
                                  "X-RateLimit-IP-Remaining") if h in r.headers}
            try:
                body = r.json()
            except ValueError:
                body = None
            if body is None:
                record.update({"ok": False, "conclusion": f"非 JSON 响应",
                               "body_head": r.text[:160]})
            elif kind == "catalog":
                # capabilities: 200 + interfaces/name 结构
                if r.status_code == 200 and isinstance(body, dict) and (
                        "interfaces" in body or "name" in body):
                    record.update({"ok": True, "conclusion": "目录通过",
                                   "interfaces": body.get("count"),
                                   "detail": body if "name" in body and "interfaces" not in body else None})
                    if "name" in body:
                        record["capability"] = {k: body.get(k) for k in
                                                ("enabled", "required", "required_any",
                                                 "methods", "provider", "max_limit",
                                                 "probe_supported", "description")}
                        record.pop("detail", None)
                else:
                    record.update({"ok": False, "conclusion": "目录异常",
                                   "body_head": json.dumps(body, ensure_ascii=False)[:200]})
            else:
                data = body.get("data") or {}
                fields = data.get("fields") or []
                items = data.get("items") or []
                record.update({"code": body.get("code"),
                               "ok_flag": body.get("ok"),
                               "error": body.get("error"),
                               "msg": (body.get("msg") or body.get("message") or "")[:160],
                               "count": body.get("count"),
                               "fields": fields, "rows": len(items)})
                if items:
                    record["sample_row"] = items[0]
                    if len(items) > 1:
                        record["sample_last"] = items[-1]
                if r.status_code == 200 and body.get("code") == 0 and body.get("ok") is not False:
                    record["ok"] = True
                    if kind == "probe":
                        record["conclusion"] = "探测通过（仅本地样本，≤5行）"
                    elif not items:
                        record["conclusion"] = "正式请求通过（空结果）"
                    else:
                        record["conclusion"] = "正式请求通过"
                        # 数据时间: 尝试从行内日期列提取
                        for col in ("trade_date", "cal_date", "end_date", "ann_date"):
                            if col in fields:
                                idx = fields.index(col)
                                vals = sorted({str(row[fields.index(col)]) for row in items if len(row) > idx})
                                record["data_date_range"] = [vals[0], vals[-1]] if len(vals) > 1 else vals
                                break
                elif r.status_code in (401, 403):
                    record["ok"] = False
                    record["conclusion"] = "鉴权失败（密钥无效/缺失）"
                elif r.status_code == 429:
                    record["ok"] = False
                    record["conclusion"] = "限流 429"
                elif r.status_code == 503:
                    record["ok"] = False
                    record["conclusion"] = f"未启用/暂不可用 503: {body.get('error', '')}"
                elif r.status_code == 502:
                    record["ok"] = False
                    record["conclusion"] = f"上游失败 502: {(body.get('msg') or body.get('message') or '')[:80]}"
                elif r.status_code == 504:
                    record["ok"] = False
                    record["conclusion"] = "上游超时 504"
                elif r.status_code == 400:
                    record["ok"] = False
                    record["conclusion"] = f"参数/路径错误 400: {(body.get('msg') or body.get('message') or body.get('error') or '')[:80]}"
                elif r.status_code == 404:
                    record["ok"] = False
                    record["conclusion"] = "接口未注册 404"
                else:
                    record["ok"] = False
                    record["conclusion"] = f"其他 HTTP {r.status_code} 业务码 {body.get('code')}"
    except Exception as exc:  # 兜底，不让单条探测中断整个脚本
        record.update({"ok": False, "conclusion": f"异常: {type(exc).__name__}",
                       "detail": str(exc)[:160]})
    record["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
    RESULTS.append(record)
    flag = "✓" if record.get("ok") else "✗"
    print(f"  {flag} [{provider:9s}] {name:34s} HTTP {str(record.get('http_status', '-')):>3} "
          f"rows={record.get('rows', '-'):>4} {record.get('conclusion', '')}"
          + (f" | msg={record['msg'][:60]}" if record.get("msg") else ""))
    return record


def main() -> int:
    settings.ensure_dirs()
    today = date.today()
    d10 = (today - timedelta(days=10)).strftime("%Y%m%d")
    d_today = today.strftime("%Y%m%d")
    period = _last_quarter_end(today)

    print(f"=== Datahubco 基础版 ({settings.DATAHUBCO_BASE_URL}) ===")
    dh = _client(settings.DATAHUBCO_BASE_URL, settings.DATAHUBCO_READ_TIMEOUT)

    # -- 第一步: 交易日历，确定最近已完成交易日（不把示例日期固定为生产默认值）
    probe(dh, "datahubco", "/trade_cal",
          {"exchange": "SSE", "start_date": (today - timedelta(days=30)).strftime("%Y%m%d"),
           "end_date": d_today, "fields": "exchange,cal_date,is_open,pretrade_date"},
          name="trade_cal SSE 近30天", kind="formal")
    latest = None
    try:
        r = dh.get("/trade_cal", params={
            "exchange": "SSE", "start_date": (today - timedelta(days=30)).strftime("%Y%m%d"),
            "end_date": d_today, "fields": "exchange,cal_date,is_open,pretrade_date"},
            headers={"X-API-Key": settings.DATAHUBCO_API_KEY})
        rows = (r.json().get("data") or {}).get("items", [])
        open_dates = sorted(str(row[1]) for row in rows if str(row[2]) == "1")
        latest = open_dates[-1] if open_dates else None
    except Exception as exc:
        print(f"  交易日历解析失败: {exc}")
    print(f"  → 最近开市日: {latest or '未取得'} (今天={today})")
    d = latest or d_today
    win_start = (today - timedelta(days=3)).isoformat()
    half_period = _last_quarter_end(today)

    # -- stock-basic 别名核对（用户示例 vs 手册名）
    probe(dh, "datahubco", "/stock-basic", {"limit": 3}, name="stock-basic（用户示例别名）", kind="formal")
    probe(dh, "datahubco", "/stock_basic", {"limit": 3}, name="stock_basic（手册名）", kind="formal")
    probe(dh, "datahubco", "/stock_basic",
          {"list_status": "L", "limit": 5, "fields": "ts_code,symbol,name,area,industry,market,list_date"},
          name="stock_basic 带筛选", kind="formal")

    # -- 核心 K 线链路
    probe(dh, "datahubco", "/daily",
          {"ts_code": "000001.SZ", "trade_date": d,
           "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"},
          name="daily 单日 000001.SZ", kind="formal")
    probe(dh, "datahubco", "/daily",
          {"ts_code": "600519.SH", "start_date": d10, "end_date": d,
           "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"},
          name="daily 区间 600519.SH", kind="formal")
    probe(dh, "datahubco", "/daily_basic",
          {"ts_code": "000001.SZ", "trade_date": d,
           "fields": "ts_code,trade_date,close,turnover_rate,volume_ratio,pe_ttm,pb,ps,total_mv,circ_mv,total_share,float_share"},
          name="daily_basic 单日", kind="formal")
    probe(dh, "datahubco", "/adj_factor",
          {"ts_code": "000001.SZ", "start_date": d10, "end_date": d,
           "fields": "ts_code,trade_date,adj_factor"},
          name="adj_factor 区间", kind="formal")
    probe(dh, "datahubco", "/index_daily",
          {"ts_code": "000300.SH", "start_date": d10, "end_date": d,
           "fields": "ts_code,trade_date,close,open,high,low,vol,amount"},
          name="index_daily 沪深300", kind="formal")

    # -- 财务/资金/涨跌停/行业（权限待验证）
    probe(dh, "datahubco", "/fina_indicator", {"ts_code": "600519.SH", "period": half_period},
          name="fina_indicator 最近报告期", kind="formal")
    probe(dh, "datahubco", "/income", {"ts_code": "600519.SH", "period": half_period},
          name="income 利润表", kind="formal")
    probe(dh, "datahubco", "/balancesheet", {"ts_code": "600519.SH", "period": half_period},
          name="balancesheet 资产负债表", kind="formal")
    probe(dh, "datahubco", "/cashflow", {"ts_code": "600519.SH", "period": half_period},
          name="cashflow 现金流量表", kind="formal")
    probe(dh, "datahubco", "/dividend", {"ts_code": "600519.SH", "limit": 5},
          name="dividend 分红", kind="formal")
    probe(dh, "datahubco", "/moneyflow",
          {"ts_code": "000001.SZ", "start_date": d10, "end_date": d, "limit": 10},
          name="moneyflow 个股资金", kind="formal")
    probe(dh, "datahubco", "/stk_limit", {"trade_date": d, "limit": 5},
          name="stk_limit 涨跌停价", kind="formal")
    probe(dh, "datahubco", "/index_classify", {"src": "SW2021", "level": "L1", "limit": 10},
          name="index_classify SW2021 L1", kind="formal")
    probe(dh, "datahubco", "/index_member_all", {"l1_code": "110000", "is_new": "Y", "limit": 5},
          name="index_member_all 申万成分", kind="formal")
    probe(dh, "datahubco", "/index_weekly", {"ts_code": "000300.SH", "start_date": d10, "end_date": d},
          name="index_weekly", kind="formal")
    probe(dh, "datahubco", "/index_monthly", {"ts_code": "000300.SH", "start_date": "20260101", "end_date": d},
          name="index_monthly", kind="formal")
    dh.close()

    print(f"\n=== ProMax Relay ({settings.PROMAX_BASE_URL}) ===")
    pm = _client(settings.PROMAX_BASE_URL, settings.PROMAX_READ_TIMEOUT)

    # -- 能力目录（服务根地址，不在 /tushare/pro 下）
    probe(pm, "promax", settings.PROMAX_CAPABILITIES_URL, {}, name="/tushare/capabilities 目录", kind="catalog")
    for api in ("daily", "adj_factor", "pro_bar", "news", "major_news", "top10_holders",
                "sw_daily", "moneyflow_mkt_dc", "index_classify", "index_member_all",
                "dividend", "trade_cal", "stock_basic", "income", "fina_indicator",
                "moneyflow", "daily_basic", "index_daily"):
        probe(pm, "promax", f"{settings.PROMAX_CAPABILITIES_URL}/{api}", {},
              name=f"capabilities/{api}", kind="catalog")

    # -- 正式业务请求
    probe(pm, "promax", "/daily", {"ts_code": "000001.SZ", "start_date": d10, "end_date": d, "limit": 5},
          name="daily 区间", kind="formal")
    probe(pm, "promax", "/daily", {"trade_date": d, "limit": 5},
          name="daily 全市场单日", kind="formal")
    probe(pm, "promax", "/adj_factor", {"ts_code": "000001.SZ", "start_date": d10, "end_date": d, "limit": 5},
          name="adj_factor", kind="formal")
    probe(pm, "promax", "/pro_bar",
          {"ts_code": "000001.SZ", "freq": "D", "asset": "E", "adj": "qfq",
           "start_date": d10, "end_date": d, "limit": 5},
          name="pro_bar qfq", kind="formal")
    probe(pm, "promax", "/stock_basic", {"exchange": "SSE", "list_status": "L", "limit": 5},
          name="stock_basic SSE", kind="formal")
    probe(pm, "promax", "/trade_cal", {"exchange": "SSE", "start_date": d10, "end_date": d},
          name="trade_cal", kind="formal")
    probe(pm, "promax", "/index_daily", {"ts_code": "000300.SH", "start_date": d10, "end_date": d, "limit": 5},
          name="index_daily", kind="formal")
    probe(pm, "promax", "/top10_holders", {"ts_code": "600519.SH", "limit": 10},
          name="top10_holders 十大股东", kind="formal")
    probe(pm, "promax", "/sw_daily", {"ts_code": "801010.SI", "start_date": d10, "end_date": d},
          name="sw_daily 申万日线", kind="formal")
    probe(pm, "promax", "/index_classify", {"src": "SW2021", "level": "L1"},
          name="index_classify SW2021 L1", kind="formal")
    probe(pm, "promax", "/index_member_all", {"l1_code": "110000", "is_new": "Y", "limit": 5},
          name="index_member_all 农林牧渔成分", kind="formal")
    probe(pm, "promax", "/moneyflow_mkt_dc", {"trade_date": d},
          name="moneyflow_mkt_dc 大盘资金", kind="formal")
    probe(pm, "promax", "/dividend", {"ts_code": "600519.SH", "limit": 5},
          name="dividend", kind="formal")

    # -- 新闻（显式来源与时间窗；空窗口做多种写法核对）
    win_start = f"{win_start} 00:00:00"
    win_end = f"{today.isoformat()} 23:59:59"
    probe(pm, "promax", "/news", {"src": "cls", "start_date": win_start, "end_date": win_end, "limit": 10},
          name="news cls 完整时间窗", kind="formal")
    probe(pm, "promax", "/news", {"src": "cls", "start_date": d10, "end_date": d, "limit": 10},
          name="news cls YYYYMMDD 窗", kind="formal")
    probe(pm, "promax", "/major_news", {"src": "cls", "start_date": win_start, "end_date": win_end, "limit": 10},
          name="major_news 快讯", kind="formal")
    pm.close()

    print("\n=== 汇总 ===")
    ok = sum(1 for r in RESULTS if r.get("ok"))
    print(f"通过 {ok}/{len(RESULTS)}")
    out = Path("/tmp/stockpanel_probe_results.json")
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"明细已写入 {out}")
    return 0


def _last_quarter_end(today: date) -> str:
    """最近一个大概率已披露的报告期（上一季度末）。"""
    month = ((today.month - 1) // 3) * 3 + 3
    year = today.year
    month -= 3
    if month <= 0:
        month += 12
        year -= 1
    return f"{year}{month:02d}{'31' if month in (3, 12) else '30'}"


if __name__ == "__main__":
    sys.exit(main())
