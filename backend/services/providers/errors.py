"""数据源统一错误体系（design.md §4.1.6）。

统一 API 错误对象: error/message/retryable/request_id，脱敏后返回给路由层，
由 FastAPI 异常处理器映射为对应 HTTP 状态码：
    参数错误          -> 400
    缺配置/能力不可用 -> 503
    上游协议失败      -> 502
    总超时            -> 504
    限流              -> 429（附等待提示）
上游鉴权失败映射为配置问题（503），不误报为用户登录失效。
"""
from __future__ import annotations


class DataSourceError(Exception):
    """数据源错误基类。message 中禁止出现密钥。"""

    kind = "provider_error"
    http_status = 502
    retryable = False

    def __init__(self, message: str, *, provider: str | None = None,
                 api: str | None = None, request_id: str | None = None,
                 retryable: bool | None = None, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.api = api
        self.request_id = request_id
        if retryable is not None:
            self.retryable = retryable
        self.detail = (detail or "")[:300]

    def to_dict(self) -> dict:
        return {
            "error": self.kind,
            "message": self.message,
            "retryable": self.retryable,
            "provider": self.provider,
            "api": self.api,
            "request_id": self.request_id,
        }


class DataSourceConfigError(DataSourceError):
    """后端缺配置（密钥未配置 / HTTP 未显式允许 / 模式缺密钥）。"""
    kind = "source_config_error"
    http_status = 503


class DataSourceAuthError(DataSourceError):
    """上游鉴权失败（401/403 或等价业务错误）→ 配置/权限问题，不重试。"""
    kind = "source_auth_error"
    http_status = 503


class DataSourceUnavailableError(DataSourceError):
    """能力未启用（503 data_source_unavailable / 404 unknown_api）或上游池耗尽。

    retryable 由调用方按 error 分类决定（池耗尽可退避重试，未启用不重试）。
    """
    kind = "source_unavailable"
    http_status = 503


class DataSourceProtocolError(DataSourceError):
    """上游协议失败（非 JSON、缺列、行宽不符、分页异常、业务失败码）。"""
    kind = "source_protocol_error"
    http_status = 502


class DataSourceRateLimitError(DataSourceError):
    """上游限流（429），携带 Retry-After 等待秒数。"""
    kind = "source_rate_limited"
    http_status = 429

    def __init__(self, message: str, *, retry_after: float = 0.0, **kw):
        super().__init__(message, retryable=True, **kw)
        self.retry_after = retry_after


class DataSourceTimeoutError(DataSourceError):
    """请求链总预算耗尽（504）。"""
    kind = "source_timeout"
    http_status = 504
    retryable = False


class DataSourceParamError(DataSourceError):
    """我方发出的请求参数不合法（400 invalid_params / invalid api name）。"""
    kind = "source_param_error"
    http_status = 400
