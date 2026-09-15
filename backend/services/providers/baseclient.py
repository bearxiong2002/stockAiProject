"""双源 HTTP 客户端基座（design.md §4.1.6）。

- 复用连接的同步 httpx.Client（trust_env/TLS 可配置）
- 信封解析: HTTP 状态 -> 业务码/ok -> fields/items 校验（按字段名映射）
- 有界退避重试（仅可恢复错误），遵守 Retry-After；请求链总预算 deadline
- 客户端侧保守限流: 并发信号量 + （ProMax）最小请求间隔
- 分页: limit/offset 成对、短页终止、重复页检测、最大页数/行数保护
- X-Request-Id 生成与回传；密钥只进请求头，绝不写日志
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from config import settings
from services.providers.errors import (
    DataSourceAuthError,
    DataSourceParamError,
    DataSourceProtocolError,
    DataSourceRateLimitError,
    DataSourceTimeoutError,
    DataSourceUnavailableError,
)

# 视为"未启用"的 503 错误类别（不重试）；upstream_pool_exhausted 属临时耗尽，可退避重试
_NON_RETRYABLE_503 = {"data_source_unavailable", "minute_data_pending"}

# 上游对区间长度限制（实测 "requested date range is too large"，365 天可用 → 保守 350）
RANGE_CHUNK_DAYS = 350


@dataclass
class FetchResult:
    """一次（可能分页的）原始拉取结果。"""

    provider: str
    api: str
    fields: list[str]
    rows: list[list]
    request_id: str | None = None
    fetched_at: float = 0.0
    elapsed_ms: int = 0
    pages: int = 1
    warnings: list[str] = None  # type: ignore[assignment]
    upstream_meta: dict | None = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class _RateLimiter:
    """简单节奏器: 相邻请求最小间隔（秒）。"""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


class SourceClient:
    """一个数据供应商的同步 HTTP 客户端（连接池复用，线程安全到"每次请求"级）。"""

    provider = "unset"
    read_timeout_attr = "DATAHUBCO_READ_TIMEOUT"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._semaphore = threading.BoundedSemaphore(max(1, settings.STOCK_MAX_CONCURRENCY))
        self._limiter = _RateLimiter(self.min_interval)
        self._client = self._build_client(transport)
        self._closed = False

    # -- 子类配置点 ---------------------------------------------------------

    min_interval: float = 0.0

    def base_url(self) -> str:
        raise NotImplementedError

    def api_key(self) -> str:
        raise NotImplementedError

    def config_problems(self) -> list[str]:
        """配置检查: 返回问题列表（空 = 可用）。"""
        problems: list[str] = []
        if not self.api_key():
            problems.append("API Key 未配置")
        if (self.base_url().startswith("http://")
                and self.http_needs_explicit_allow()
                and not settings.DATAHUBCO_ALLOW_HTTP):
            problems.append("明文 HTTP 地址需显式允许（DATAHUBCO_ALLOW_HTTP=true）")
        return problems

    def http_needs_explicit_allow(self) -> bool:
        return False

    def read_timeout(self) -> float:
        return float(getattr(settings, self.read_timeout_attr))

    def _build_client(self, transport: httpx.BaseTransport | None) -> httpx.Client:
        ca = settings.STOCK_CA_FILE or None
        return httpx.Client(
            base_url=self.base_url(),
            timeout=httpx.Timeout(
                connect=settings.STOCK_HTTP_CONNECT_TIMEOUT,
                read=self.read_timeout(),
                write=10,
                pool=self.read_timeout(),
            ),
            trust_env=settings.STOCK_HTTP_TRUST_ENV,
            verify=ca if ca else True,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        if self._client and not self._closed:
            self._client.close()
            self._closed = True

    # -- 请求入口 -----------------------------------------------------------

    def get_rows(self, api: str, params: dict, *, deadline: float | None = None) -> FetchResult:
        """单页请求（含有界重试）→ FetchResult。"""
        started = time.monotonic()
        attempt = 0
        request_id: str | None = None
        err: DataSourceError | None = None
        while True:
            self._check_deadline(deadline, started)
            with self._semaphore:
                self._check_deadline(deadline, started)
                self._limiter.wait()
                request_id = uuid.uuid4().hex[:16]
                headers = {"X-API-Key": self.api_key(), "X-Request-Id": request_id}
                try:
                    resp = self._client.get(f"/{api.lstrip('/')}", params=params,
                                            headers=headers)
                    http_err = None
                except httpx.TimeoutException as exc:
                    http_err = DataSourceTimeoutError(
                        "上游请求超时", provider=self.provider, api=api,
                        request_id=request_id, retryable=True)
                except httpx.HTTPError as exc:
                    http_err = DataSourceProtocolError(
                        f"网络错误: {type(exc).__name__}", provider=self.provider,
                        api=api, request_id=request_id, retryable=True)

            if http_err is None:
                err = self._parse_error(resp, request_id)
                if err is None:
                    body = resp.json()
                    data = body.get("data") or {}
                    fields = data.get("fields") or []
                    items = data.get("items") or []
                    self._validate_envelope(fields, items, api=api, request_id=request_id)
                    return FetchResult(
                        provider=self.provider, api=api,
                        fields=[str(f) for f in fields], rows=items,
                        request_id=request_id, fetched_at=time.time(),
                        elapsed_ms=round((time.monotonic() - started) * 1000),
                        upstream_meta=self._upstream_headers(resp))
                if not (err.retryable and attempt < max(0, settings.STOCK_MAX_RETRIES)):
                    raise err
            elif not (http_err.retryable and attempt < max(0, settings.STOCK_MAX_RETRIES)):
                raise http_err

            wait = self._backoff(attempt, http_err or err)  # type: ignore[arg-type]
            if deadline is not None and time.monotonic() + wait > deadline:
                raise DataSourceTimeoutError(
                    "请求链总预算耗尽（重试等待超出）", provider=self.provider,
                    api=api, request_id=request_id)
            attempt += 1
            time.sleep(wait)

    def fetch_all(self, api: str, params: dict, *, fields: str | None = None,
                  page_size: int = 5000, max_pages: int = 20, max_rows: int = 200_000,
                  deadline: float | None = None) -> FetchResult:
        """limit/offset 分页聚合: 短页终止、重复页检测、页数/行数上限保护。

        返回的 FetchResult.pages/warnings 记录分页过程；调用方负责按主键去重校验。
        """
        started = time.monotonic()
        all_rows: list[list] = []
        merged_fields: list[str] | None = None
        warnings: list[str] = []
        pages = 0
        offset = 0
        upstream_meta: dict | None = None
        request_id: str | None = None
        while pages < max_pages:
            self._check_deadline(deadline, started)
            if len(all_rows) >= max_rows:
                warnings.append(f"达到最大行数保护 {max_rows}，结果可能不完整")
                break
            page_params = dict(params)
            page_params["limit"] = page_size
            page_params["offset"] = offset
            if fields:
                page_params["fields"] = fields
            try:
                result = self.get_rows(api, page_params, deadline=deadline)
            except DataSourceProtocolError as exc:
                # 网关响应过大(413/too large) → 页减半后同 offset 重试（最多 3 次）
                msg = str(exc.message)
                if (("too large" in msg or "413" in msg) and page_size > 500):
                    page_size //= 2
                    if page_size < 500:
                        raise
                    warnings.append(f"响应过大，页大小调整为 {page_size}")
                    continue
                raise
            request_id = result.request_id
            upstream_meta = result.upstream_meta
            if merged_fields is None:
                merged_fields = result.fields
            elif result.rows and result.fields != merged_fields:
                warnings.append("分页字段列表发生变化，以首页为准")
            # 重复页检测: 整页与上一页完全一致 → 服务端忽略 offset，终止并告警
            if (all_rows and result.rows and len(all_rows) >= len(result.rows)
                    and all_rows[-len(result.rows):] == result.rows):
                warnings.append("检测到重复页（offset 未生效），已终止分页")
                break
            all_rows.extend(result.rows)
            pages += 1
            if len(result.rows) < page_size:
                break
            offset += page_size
        else:
            warnings.append(f"达到最大页数 {max_pages}，结果可能不完整")
        if merged_fields is None:
            merged_fields = []
            warnings.append("分页未取得任何数据")
        return FetchResult(provider=self.provider, api=api, fields=merged_fields,
                           rows=all_rows, request_id=request_id, fetched_at=time.time(),
                           elapsed_ms=round((time.monotonic() - started) * 1000),
                           pages=pages, warnings=warnings, upstream_meta=upstream_meta)

    # -- 日期分窗（上游对区间长度有限制: "requested date range is too large"） --

    def fetch_date_chunks(self, api: str, params: dict, start_date: str, end_date: str,
                          *, fields: str | None = None, chunk_days: int = 350,
                          max_chunks: int = 8, deadline: float | None = None) -> FetchResult:
        """按日期窗口分段拉取区间数据（每窗 ≤ chunk_days 自然日）。

        窗口成对且不与 trade_date 混用；合并后行按窗口顺序自然升序（每窗内部升序）。
        """
        started = time.monotonic()
        all_rows: list[list] = []
        fields_out: list[str] | None = None
        warnings: list[str] = []
        request_id: str | None = None
        upstream_meta: dict | None = None
        chunks = 0
        cur_end = end_date
        # 从后往前切窗，保证最新数据先到（超时/失败时截断在前端更早的历史）
        windows: list[tuple[str, str]] = []
        cursor = end_date
        while cursor >= start_date and chunks < max_chunks:
            win_start = self._shift_days(cursor, chunk_days - 1)
            win_start = max(win_start, start_date)
            windows.append((win_start, cursor))
            if win_start == start_date:
                break
            # 下一窗结束于本窗开始的前一天（_shift_days 为减法，负数才会前进）
            cursor = self._shift_days(win_start, 1)
            chunks += 1
        else:
            if cursor > start_date:
                warnings.append(f"日期窗口超出 {max_chunks} 段上限，历史可能不完整")
        if not windows:
            windows = [(start_date, end_date)]
        for win_start, win_end in windows:
            win_params = dict(params or {})
            win_params.update({"start_date": win_start, "end_date": win_end})
            if fields:
                win_params["fields"] = fields
            result = self.get_rows(api, win_params, deadline=deadline)
            request_id = result.request_id
            upstream_meta = result.upstream_meta
            if fields_out is None:
                fields_out = result.fields
            all_rows.extend(result.rows)
        if fields_out is None:
            fields_out = []
            warnings.append("区间未取得任何数据")
        return FetchResult(provider=self.provider, api=api, fields=fields_out,
                           rows=all_rows, request_id=request_id, fetched_at=time.time(),
                           elapsed_ms=round((time.monotonic() - started) * 1000),
                           pages=len(windows), warnings=warnings,
                           upstream_meta=upstream_meta)

    @staticmethod
    def _shift_days(yyyymmdd: str, days: int) -> str:
        d = datetime.strptime(yyyymmdd, "%Y%m%d") - timedelta(days=days)
        return d.strftime("%Y%m%d")

    @staticmethod
    def _span_days(start_date: str, end_date: str) -> int:
        return (datetime.strptime(end_date, "%Y%m%d")
                - datetime.strptime(start_date, "%Y%m%d")).days

    # -- DataFrame 便捷 ------------------------------------------------------

    def df(self, api: str, params: dict, *, deadline: float | None = None):
        return self._to_df(self.get_rows(api, params, deadline=deadline))

    def fetch_all_df(self, api: str, params: dict, *, fields: str | None = None,
                     deadline: float | None = None, **kw):
        return self._to_df(self.fetch_all(api, params, fields=fields, deadline=deadline, **kw))

    @staticmethod
    def _to_df(result: FetchResult):
        import pandas as pd

        frame = (pd.DataFrame(result.rows, columns=result.fields) if result.rows
                 else pd.DataFrame(columns=result.fields))
        frame.attrs["fetch"] = {
            "provider": result.provider, "api": result.api,
            "fetched_at": result.fetched_at, "request_id": result.request_id,
            "pages": result.pages, "warnings": result.warnings,
            "upstream_meta": result.upstream_meta,
        }
        return frame

    # -- 响应解析与错误分类 ---------------------------------------------------

    def _check_deadline(self, deadline: float | None, started: float) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise DataSourceTimeoutError("请求链总预算耗尽", provider=self.provider)

    def _backoff(self, attempt: int, err: DataSourceError) -> float:
        if isinstance(err, DataSourceRateLimitError) and err.retry_after:
            return min(err.retry_after, 30.0)
        return min(1.0 * (2 ** attempt) + random.uniform(0, 0.3), 8.0)

    def _upstream_headers(self, resp: httpx.Response) -> dict:
        out = {}
        for h in ("X-Data-Source", "X-Cache", "X-RateLimit-Remaining",
                  "X-RateLimit-IP-Remaining"):
            if h in resp.headers:
                out[h] = resp.headers[h]
        return out

    def _parse_error(self, resp: httpx.Response, request_id: str | None) -> DataSourceError | None:
        """HTTP/业务层错误分类。None = 业务成功，可继续解析 rows。"""
        status = resp.status_code
        body = self._safe_json(resp)
        if body is None:
            hint = "响应过大(413)" if status == 413 else "响应非 JSON"
            raise DataSourceProtocolError(hint, provider=self.provider,
                                          request_id=request_id)
        request_id = body.get("request_id") or request_id

        if status == 200:
            if body.get("ok") is False:
                # ProMax 错误信封 {ok:false, error, message}
                error = str(body.get("error") or "")
                message = str(body.get("message") or body.get("msg") or "")
                if error == "rate_limited":
                    return DataSourceRateLimitError(
                        message or "rate_limited",
                        retry_after=float(resp.headers.get("Retry-After", 0) or 0),
                        provider=self.provider, request_id=request_id)
                if error == "invalid_params":
                    return DataSourceParamError(
                        f"上游参数错误: {message or error}", provider=self.provider,
                        request_id=request_id)
                if error == "unknown_api":
                    return DataSourceUnavailableError(
                        f"接口未注册: {message or error}", provider=self.provider,
                        request_id=request_id)
                if error == "upstream_timeout":
                    return DataSourceTimeoutError(
                        f"上游超时: {message or error}", provider=self.provider,
                        request_id=request_id)
                return DataSourceUnavailableError(
                    f"上游不可用: {error or message or 'ok=false'}",
                    provider=self.provider, request_id=request_id,
                    retryable=error == "upstream_pool_exhausted")
            code = body.get("code", 0)
            if isinstance(code, int) and code != 0:
                msg = str(body.get("msg") or body.get("message") or "")
                if "token" in msg.lower() or "api key" in msg.lower() or "key" == msg.lower():
                    return DataSourceAuthError(msg, provider=self.provider,
                                               request_id=request_id)
                return DataSourceProtocolError(
                    f"业务失败码 {code}: {msg}", provider=self.provider,
                    request_id=request_id)
            if "data" not in body:
                raise DataSourceProtocolError("响应缺少 data 字段",
                                              provider=self.provider, request_id=request_id)
            return None

        message = str(body.get("message") or body.get("msg") or body.get("error") or "")
        if status in (401, 403):
            return DataSourceAuthError(f"上游鉴权失败({status}): {message}",
                                       provider=self.provider, request_id=request_id)
        if status == 400:
            return DataSourceParamError(f"上游参数错误(400): {message}",
                                        provider=self.provider, request_id=request_id)
        if status == 404:
            return DataSourceUnavailableError(f"接口未注册(404): {message}",
                                              provider=self.provider,
                                              request_id=request_id)
        if status == 405:
            return DataSourceProtocolError(f"方法不允许(405): {message}",
                                           provider=self.provider, request_id=request_id)
        if status == 413:
            return DataSourceProtocolError(f"响应过大(413): {message or 'too large'}",
                                           provider=self.provider,
                                           request_id=request_id)
        if status == 429:
            return DataSourceRateLimitError(
                "上游限流(429)",
                retry_after=float(resp.headers.get("Retry-After", 0) or 0),
                provider=self.provider, request_id=request_id)
        if status == 503:
            error = str(body.get("error") or "")
            retryable = error not in _NON_RETRYABLE_503
            return DataSourceUnavailableError(
                f"上游不可用(503): {error or message}", provider=self.provider,
                request_id=request_id, retryable=retryable)
        if status == 504:
            return DataSourceTimeoutError(f"上游超时(504): {message}",
                                          provider=self.provider, request_id=request_id)
        if status == 502:
            # 基础版 502 可能包装上游权限/参数错误：先解析分类，不盲重试
            lowered = message.lower()
            retryable = not any(k in lowered for k in
                                ("permission", "权限", "积分", "field", "api name"))
            return DataSourceProtocolError(f"上游失败(502): {message}",
                                           provider=self.provider,
                                           request_id=request_id, retryable=retryable)
        return DataSourceProtocolError(
            f"上游异常 HTTP {status}: {message}", provider=self.provider,
            request_id=request_id, retryable=500 <= status < 600)

    def _safe_json(self, resp: httpx.Response) -> dict | None:
        try:
            body = resp.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _validate_envelope(self, fields, items, *, api: str, request_id: str | None) -> None:
        if not isinstance(fields, list) or not isinstance(items, list):
            raise DataSourceProtocolError("data.fields/data.items 类型错误",
                                          provider=self.provider, api=api,
                                          request_id=request_id)
        if items and not fields:
            raise DataSourceProtocolError("有数据行但缺少字段列表",
                                          provider=self.provider, api=api,
                                          request_id=request_id)
        if len(set(map(str, fields))) != len(fields):
            raise DataSourceProtocolError("fields 含重复字段", provider=self.provider,
                                          api=api, request_id=request_id)
        width = len(fields)
        for row in items[:5]:
            if not isinstance(row, list) or len(row) != width:
                got = len(row) if isinstance(row, list) else "?"
                raise DataSourceProtocolError(
                    f"行宽({got})与 fields({width}) 不符", provider=self.provider,
                    api=api, request_id=request_id)
