"""股票数据源 provider 包（design.md §4.1.3–§4.1.6，阶段3）。

- datahubco: Datahubco 基础版（主源）
- promax:    ProMax Relay（扩展/备用）
- mock:      显式模拟模式
- normalize: 字段映射与单位换算
- baseclient/errors: HTTP 客户端基座与统一错误体系

模式路由（STOCK_DATA_MODE）:
    mock       仅模拟数据
    datahubco  仅基础版
    promax     仅 ProMax
    hybrid     按接口路由主备源（design.md §4.1.4 映射表）
"""
from __future__ import annotations

from services.providers.baseclient import FetchResult, SourceClient
from services.providers.datahubco import DatahubcoSource
from services.providers.errors import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceError,
    DataSourceParamError,
    DataSourceProtocolError,
    DataSourceRateLimitError,
    DataSourceTimeoutError,
    DataSourceUnavailableError,
)
from services.providers.mock import MockSource
from services.providers.promax import ProMaxSource

__all__ = [
    "FetchResult", "SourceClient",
    "DatahubcoSource", "ProMaxSource", "MockSource",
    "DataSourceError", "DataSourceAuthError", "DataSourceConfigError",
    "DataSourceParamError", "DataSourceProtocolError",
    "DataSourceRateLimitError", "DataSourceTimeoutError",
    "DataSourceUnavailableError",
]
