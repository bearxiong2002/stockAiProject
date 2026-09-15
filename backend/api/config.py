"""系统配置/缓存路由 /api/config/*（阶段3 缓存管理 + 数据源状态；阶段8 配置 CRUD 与 LLM 测试）。

- GET  /api/config            非敏感配置（LLM 脱敏视图 + 应用信息），不回显任何密钥
- PUT  /api/config            更新 LLM 配置（密钥加密存储，见 services/llm_config.py）
- POST /api/config/test-llm   测试 LLM 连接（可用未保存的表单值覆盖）
股票数据源密钥仍由环境变量独占（design.md §4.1.6），不经此接口读写。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from config import settings
from models.schemas import (AppInfoView, CacheStatsResponse, ClearCacheResponse,
                            ConfigResponse, ConfigUpdateRequest, LLMConfigView,
                            LLMTestRequest, LLMTestResponse)
from services.ai_analyzer import AIAnalyzer
from services.cache import clear_cache, get_cache_stats
from services.data_fetcher import get_data_fetcher
from services.llm_config import (get_llm_config, provider_defaults,
                                 public_llm_view, update_llm_config)

logger = logging.getLogger("stockpanel.config")

router = APIRouter(prefix="/api/config", tags=["config"])


def _app_info() -> AppInfoView:
    dist = settings.FRONTEND_DIST
    return AppInfoView(
        version=settings.APP_VERSION,
        server_port=settings.SERVER_PORT,
        data_dir=str(settings.APP_DATA_DIR),
        serve_static=bool(settings.SERVE_STATIC and (dist / "index.html").is_file()),
        frontend_dist=str(dist),
        frontend_built=(dist / "index.html").is_file(),
    )


def _config_response() -> ConfigResponse:
    return ConfigResponse(app=_app_info(),
                          llm=LLMConfigView(**public_llm_view(get_llm_config())),
                          llm_defaults=provider_defaults())


@router.get("", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """获取非敏感配置（LLM 密钥只返回是否配置与掩码）。"""
    return _config_response()


@router.put("", response_model=ConfigResponse)
async def put_config(payload: ConfigUpdateRequest) -> ConfigResponse:
    """更新 LLM 配置；空字符串清空对应项，clear_api_key 显式删除密钥。"""
    provider = payload.llm_provider
    if provider is not None:
        provider = provider.strip().lower()
        if provider not in ("", "none", "claude", "openai", "custom"):
            raise HTTPException(status_code=400,
                                detail="llm_provider 仅支持 claude/openai/custom/none")
    try:
        await update_llm_config(
            provider=provider,
            api_key=payload.llm_api_key,
            api_base=payload.llm_api_base,
            model=payload.llm_model,
            clear_api_key=payload.clear_api_key,
        )
    except Exception as exc:
        logger.exception("LLM 配置写入失败")
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc
    return _config_response()


@router.post("/test-llm", response_model=LLMTestResponse)
async def test_llm(payload: LLMTestRequest | None = None) -> LLMTestResponse:
    """测试 LLM 连接（最小 ping）；未提供的字段用已保存配置补全。"""
    payload = payload or LLMTestRequest()
    override = {k: v for k, v in payload.model_dump().items() if v is not None}
    analyzer = AIAnalyzer()
    result = analyzer.test_connection(override or None)
    return LLMTestResponse(**result)


@router.get("/cache-stats", response_model=CacheStatsResponse)
def cache_stats() -> CacheStatsResponse:
    """缓存统计: JSON 文件数量与总大小。"""
    return CacheStatsResponse(**get_cache_stats())


@router.delete("/cache", response_model=ClearCacheResponse)
def clear_all_cache() -> ClearCacheResponse:
    """清空全部数据缓存。"""
    removed = clear_cache()
    return ClearCacheResponse(ok=True, removed_files=removed)


@router.get("/data-source-status")
def data_source_status():
    """数据源状态（只读）: 模式、密钥是否配置（布尔）、能力验证结论与最近错误。

    不回显密钥、不在每次读取时探测全接口（验证结论由真实 smoke 写入的
    data_source_status.json 提供）。
    """
    return get_data_fetcher().data_source_status()
