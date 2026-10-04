"""LLM 配置解析与密钥加密存储（design.md §4.4.4、§8.2）。

优先级（逐字段，高到低）: config 表（MySQL/SQLite）> 环境变量/.env > 默认值。
股票数据源密钥不在此模块（仍由环境变量独占，见 §4.1.6），两者互不影响。

密钥加密存储: 首次使用时在应用数据目录生成本机密钥文件 `secret.key`（0600），
使用 Fernet 对称加密，密文以 `enc1:` 前缀写入 config 表；密钥文件丢失时
密文不可解密，按"未配置"处理并告警，不阻塞启动。
无 cryptography 依赖时降级为 `b64:` 前缀的本地混淆（仅避免明文，非加密强度），
运行日志会提示。
"""
from __future__ import annotations

import base64
import logging
import os
import stat
from pathlib import Path

from sqlalchemy import select

from config import settings

logger = logging.getLogger("stockpanel.llm_config")

try:  # 可选依赖: 缺失时降级为本地混淆
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_FERNET = True
except ImportError:  # pragma: no cover - 环境缺依赖的分支
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment,misc]
    _HAS_FERNET = False

# config 表中的键名
KEY_PROVIDER = "llm_provider"
KEY_API_KEY = "llm_api_key"
KEY_API_BASE = "llm_api_base"
KEY_MODEL = "llm_model"

ALLOWED_PROVIDERS = ("claude", "openai", "custom")
DISABLED_PROVIDERS = ("", "none", "off", "disabled")

DEFAULT_BASES = {
    "claude": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "custom": "",
}
DEFAULT_MODELS = {
    "claude": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "custom": "",
}

# 设置页下拉建议（用户仍可自定义输入）
MODEL_SUGGESTIONS = {
    "claude": ["claude-sonnet-5", "claude-haiku-4-5", "claude-sonnet-4-5",
               "claude-opus-4-1"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "o4-mini"],
    "custom": [],
}


# ---------------------------------------------------------------------------
# 密钥加密
# ---------------------------------------------------------------------------

class SecretBox:
    """本机密钥文件 + Fernet 的加解密封装（无依赖时降级为 b64 混淆）。"""

    def __init__(self, key_path: Path | None = None):
        self._key_path = key_path or (settings.APP_DATA_DIR / "secret.key")
        self._fernet = None
        self._warned = False

    def _read_or_create_key(self) -> bytes:
        path = self._key_path
        if path.is_file():
            return path.read_bytes().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key() if _HAS_FERNET else base64.urlsafe_b64encode(
            os.urandom(32))
        # 0600 创建，避免同机其他用户读取
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        return key

    def _cipher(self):
        if self._fernet is None:
            if not _HAS_FERNET:
                if not self._warned:
                    logger.warning(
                        "未安装 cryptography，LLM 密钥使用本地混淆存储（建议 pip install cryptography）")
                    self._warned = True
                return None
            self._fernet = Fernet(self._read_or_create_key())
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        cipher = self._cipher()
        if cipher is None:
            return "b64:" + base64.urlsafe_b64encode(plaintext.encode()).decode()
        return "enc1:" + cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, stored: str) -> str | None:
        """解密失败返回 None（密钥文件丢失/被替换），由调用方按未配置处理。"""
        if not stored:
            return ""
        try:
            if stored.startswith("enc1:"):
                cipher = self._cipher()
                if cipher is None:
                    return None
                return cipher.decrypt(stored[len("enc1:"):].encode()).decode()
            if stored.startswith("b64:"):
                return base64.urlsafe_b64decode(stored[len("b64:"):].encode()).decode()
        except Exception as exc:  # InvalidToken / 编码错误
            logger.warning("LLM 密钥解密失败（%s），按未配置处理", type(exc).__name__)
            return None
        # 无前缀 = 历史明文（兼容），原样返回并在下次写入时加密
        return stored


_secret_box = SecretBox()


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------

_cache: dict | None = None


def _normalize_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    if provider in DISABLED_PROVIDERS:
        return "none"
    return provider


def _from_env() -> dict:
    return {
        "provider": _normalize_provider(settings.LLM_PROVIDER),
        "api_key": settings.LLM_API_KEY or "",
        "api_base": (settings.LLM_API_BASE or "").strip(),
        "model": (settings.LLM_MODEL or "").strip(),
        "sources": {"provider": "env", "api_key": "env", "api_base": "env", "model": "env"},
    }


def resolve_llm_config(cfg: dict) -> dict:
    """补全 provider 默认 base/model，并给出可用性判断（不修改入参）。"""
    out = dict(cfg)
    provider = out["provider"]
    sources = dict(out.get("sources") or {})
    if provider not in ALLOWED_PROVIDERS:
        if provider != "none":
            logger.warning("未知 LLM provider: %r，按未配置处理", provider)
        provider = "none"
    out["provider"] = provider
    if not out.get("api_base"):
        out["api_base"] = DEFAULT_BASES.get(provider, "")
        sources["api_base"] = "default"
    if not out.get("model"):
        out["model"] = DEFAULT_MODELS.get(provider, "")
        sources["model"] = "default"
    out["sources"] = sources
    out["available"] = bool(
        provider in ALLOWED_PROVIDERS and out.get("api_key") and out.get("api_base"))
    out["disabled_reason"] = (
        None if out["available"] else
        "未配置 LLM（设置 → AI 配置）" if provider == "none" else
        "缺少 API Key" if not out.get("api_key") else
        "缺少 API Base URL")
    return out


def _default_config() -> dict:
    cfg = _from_env()
    return resolve_llm_config(cfg)


def get_llm_config() -> dict:
    """同步读取当前生效的 LLM 配置（内存缓存；未加载时回退环境变量）。"""
    return _cache if _cache is not None else _default_config()


async def load_llm_config() -> dict:
    """从 config 表加载（启动时调用；逐字段覆盖环境变量）。"""
    global _cache
    from models.database import ConfigItem, get_session_factory

    base = _from_env()
    sources = dict(base["sources"])
    try:
        async with get_session_factory()() as session:
            rows = (await session.execute(select(ConfigItem))).scalars().all()
    except Exception as exc:
        logger.warning("LLM 配置读取失败（%s），回退环境变量", exc)
        _cache = resolve_llm_config(base)
        return _cache

    values = {r.key: r.value for r in rows}
    provider = values.get(KEY_PROVIDER)
    if provider is not None:
        base["provider"] = _normalize_provider(provider)
        sources["provider"] = "db"
    if KEY_API_KEY in values:
        decrypted = _secret_box.decrypt(values[KEY_API_KEY])
        if decrypted is not None:
            base["api_key"] = decrypted
            sources["api_key"] = "db"
    api_base = values.get(KEY_API_BASE)
    if api_base is not None and api_base.strip():
        base["api_base"] = api_base.strip()
        sources["api_base"] = "db"
    model = values.get(KEY_MODEL)
    if model is not None and model.strip():
        base["model"] = model.strip()
        sources["model"] = "db"
    base["sources"] = sources
    _cache = resolve_llm_config(base)
    logger.info("LLM 配置已加载: provider=%s available=%s",
                _cache["provider"], _cache["available"])
    return _cache


async def update_llm_config(*, provider: str | None = None, api_key: str | None = None,
                            api_base: str | None = None, model: str | None = None,
                            clear_api_key: bool = False) -> dict:
    """写入 SQLite config 表并刷新内存缓存。

    语义: 参数为 None = 不修改；空字符串 = 清空（provider 空 = 关闭 AI）；
    clear_api_key=True 显式删除已存密钥。
    """
    from models.database import ConfigItem, get_session_factory

    updates: dict[str, str] = {}
    if provider is not None:
        updates[KEY_PROVIDER] = _normalize_provider(provider)
    if clear_api_key:
        updates[KEY_API_KEY] = ""
    elif api_key is not None:
        updates[KEY_API_KEY] = _secret_box.encrypt(api_key.strip())
    if api_base is not None:
        updates[KEY_API_BASE] = api_base.strip()
    if model is not None:
        updates[KEY_MODEL] = model.strip()
    if not updates:
        return await load_llm_config()

    async with get_session_factory()() as session:
        for key, value in updates.items():
            row = (await session.execute(
                select(ConfigItem).where(ConfigItem.key == key))).scalar_one_or_none()
            if row is None:
                session.add(ConfigItem(key=key, value=value))
            else:
                row.value = value
        await session.commit()
    return await load_llm_config()


def public_llm_view(cfg: dict | None = None) -> dict:
    """脱敏后的 LLM 配置视图（不回显密钥明文）。"""
    cfg = cfg or get_llm_config()
    key = cfg.get("api_key") or ""
    return {
        "provider": cfg["provider"],
        "available": bool(cfg.get("available")),
        "disabled_reason": cfg.get("disabled_reason"),
        "model": cfg.get("model") or "",
        "api_base": cfg.get("api_base") or "",
        "api_key_configured": bool(key),
        "api_key_masked": mask_key(key),
        "sources": cfg.get("sources") or {},
    }


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def provider_defaults() -> dict:
    """设置页展示用的 provider 默认值与模型建议（非敏感）。"""
    return {
        "default_bases": DEFAULT_BASES,
        "default_models": DEFAULT_MODELS,
        "model_suggestions": MODEL_SUGGESTIONS,
        "providers": list(ALLOWED_PROVIDERS),
    }
