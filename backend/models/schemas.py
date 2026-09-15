"""Pydantic 请求/响应模型。

阶段1 定义核心模型（持仓/自选/配置/健康检查）；
阶段3 增加 K线/个股信息的 data_meta 契约；
阶段5/6/7/8 按需扩展。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    app: str = "stockpanel"


# ---------- 股票 ----------

class StockBrief(BaseModel):
    """股票简要信息（搜索结果 / 股票列表通用）"""

    code: str
    name: str
    industry: str | None = None
    market: str | None = None


class DataMeta(BaseModel):
    """数据质量元信息（design.md §4.1.7；不包含任何密钥）"""

    model_config = ConfigDict(extra="allow")  # 保留 provider/anchor 等扩展字段

    source: str
    api: str
    as_of: str | None = None
    trade_date: str | None = None
    fetched_at: float | None = None
    is_stale: bool = False
    coverage: int | None = None
    warnings: list[str] = []


class KlineResponse(BaseModel):
    """GET /api/stock/{code}/kline 响应"""

    items: list[dict[str, Any]]
    data_meta: DataMeta


class StockInfoResponse(BaseModel):
    """GET /api/stock/{code}/info 响应"""

    info: dict[str, Any]
    data_meta: DataMeta


# ---------- 缓存 ----------

class CacheStatsResponse(BaseModel):
    file_count: int = Field(..., description="缓存 JSON 文件数量")
    total_size: int = Field(..., description="总大小（字节）")
    total_size_human: str = Field(..., description="总大小（人类可读）")
    cache_dir: str = Field(..., description="缓存目录路径")


class ClearCacheResponse(BaseModel):
    ok: bool = True
    removed_files: int = Field(..., description="删除的缓存文件数")


# ---------- 持仓 ----------

class HoldingCreate(BaseModel):
    """添加持仓请求体。"""

    stock_code: str
    stock_name: str | None = None
    quantity: int = Field(..., gt=0)
    cost_price: float = Field(..., gt=0)
    buy_date: str | None = None
    notes: str | None = None


class HoldingUpdate(BaseModel):
    """修改持仓（数量/成本价/备注/买入日期）。"""

    quantity: int | None = Field(None, gt=0)
    cost_price: float | None = Field(None, gt=0)
    buy_date: str | None = None
    notes: str | None = None


# ---------- 自选股 ----------

class WatchlistCreate(BaseModel):
    code: str


class WatchlistResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    added_at: str
    sort_order: int


class WatchlistSortPayload(BaseModel):
    codes: list[str]


# ---------- 配置 ----------

class ConfigUpdate(BaseModel):
    key: str
    value: str


class AppInfoView(BaseModel):
    """应用信息（设置页"关于"区块）。"""

    version: str
    server_port: int
    data_dir: str
    serve_static: bool
    frontend_dist: str
    frontend_built: bool


class LLMConfigView(BaseModel):
    """LLM 配置脱敏视图（不回显密钥明文）。"""

    provider: str
    available: bool
    disabled_reason: str | None = None
    model: str = ""
    api_base: str = ""
    api_key_configured: bool = False
    api_key_masked: str = ""
    sources: dict[str, str] = {}


class ConfigResponse(BaseModel):
    """GET /api/config 响应。"""

    app: AppInfoView
    llm: LLMConfigView
    llm_defaults: dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    """PUT /api/config 请求体；None = 不修改，空串 = 清空。"""

    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_model: str | None = None
    clear_api_key: bool = False


class LLMTestRequest(BaseModel):
    """POST /api/config/test-llm 请求体；未提供的字段用已保存配置补全。"""

    provider: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None


class LLMTestResponse(BaseModel):
    ok: bool
    category: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    reply: str | None = None


class HoldingView(BaseModel):
    """持仓行 + 实时计算字段。"""

    model_config = ConfigDict(extra="allow")

    id: int
    stock_code: str
    stock_name: str
    quantity: int
    cost_price: float
    buy_date: str | None = None
    notes: str | None = None
    latest_price: float | None = None
    market_value: float | None = None
    profit: float | None = None
    profit_pct: float | None = None
    weight: float | None = None
    hold_days: int | None = None
    trade_date: str | None = None


class PortfolioSummary(BaseModel):
    total_market_value: float
    total_cost: float
    total_profit: float
    total_profit_pct: float
    count: int


class HoldingsResponse(BaseModel):
    """持仓列表 + 汇总。"""

    model_config = ConfigDict(extra="allow")

    holdings: list[HoldingView]
    summary: PortfolioSummary
    data_meta: dict | None = None
