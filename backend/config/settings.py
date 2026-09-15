"""应用配置。

配置优先级（高到低）: SQLite config 表 > 环境变量 > backend/.env > 默认值。
阶段3 起股票数据源配置遵循 design.md §4.1.6: 环境变量 > .env > 默认值，
不从 SQLite/配置接口接受密钥覆盖；密钥只在请求头使用，不回显、不入日志。
"""
from __future__ import annotations

import os
from pathlib import Path


def _app_data_dir() -> Path:
    """系统应用数据目录（macOS: ~/Library/Application Support, Windows: %APPDATA%）"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / "Library" / "Application Support"
    return base / "StockPanel"


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """读取 KEY=VALUE 格式的 .env；已存在的环境变量优先，不覆盖。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BACKEND_DIR / ".env")

APP_DATA_DIR = Path(
    os.environ.get("STOCKPANEL_DATA_DIR", _app_data_dir())
)

DATA_DIR: Path = APP_DATA_DIR
CACHE_DIR: Path = DATA_DIR / "cache"
LOG_DIR: Path = DATA_DIR / "logs"
DB_PATH: Path = DATA_DIR / "stockpanel.db"

# 缓存子目录（按 design.md 4.1.2）
CACHE_SUBDIRS: dict[str, str] = {
    "kline": "kline",
    "financial": "financial",
    "info": "info",
    "boards": "boards",
}

# 缓存过期时间（秒），按 design.md 4.1.2
# 注: 日K"当日交易结束后更新"在桩实现中简化为固定 24h；
#     真实数据源按 §4.1.7 以交易日历/发布时间刷新，TTL 仅兜底。
CACHE_TTL_KLINE = 24 * 3600          # 日K/资金流向等日频数据
CACHE_TTL_FINANCIAL = 7 * 24 * 3600  # 财务指标/三大报表/股东/分红等低频数据: 7 天
CACHE_TTL_DAILY = 24 * 3600          # 股票列表/板块/个股信息: 1 天
CACHE_TTL_EMPTY = 60                 # 成功空结果短缓存
# 新闻数据不缓存（design.md 4.1.2）

# 服务端口
SERVER_PORT: int = int(os.environ.get("STOCKPANEL_PORT", "18900"))

APP_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# 股票数据源（design.md §4.1.3–§4.1.8，阶段3）
# ---------------------------------------------------------------------------

# 缓存 schema 版本: 参与缓存键，结构变更时递增以隔离旧缓存
# v4: 主力净额缺测口径 + pct 单位修正 + 切窗重叠修复 → 旧口径缓存整体失效
STOCK_CACHE_SCHEMA_VERSION: str = os.environ.get("STOCK_CACHE_SCHEMA_VERSION", "4")

# 数据源模式: mock / datahubco / promax / hybrid（初始化后生效，改动需重启）
STOCK_DATA_MODE: str = os.environ.get("STOCK_DATA_MODE", "mock").strip().lower()

# 双端业务地址（可覆盖；能力目录从 ProMax 服务根地址构建）
DATAHUBCO_BASE_URL: str = os.environ.get(
    "DATAHUBCO_BASE_URL", "http://datahubco.com/app-api/openapi/v1/tushare"
).rstrip("/")
PROMAX_BASE_URL: str = os.environ.get(
    "PROMAX_BASE_URL", "https://pcd.mobcvb.cn/tushare/pro"
).rstrip("/")


def _promax_capabilities_url(base: str) -> str:
    # https://host/tushare/pro -> https://host/tushare/capabilities（不在 /tushare/pro 下）
    root = base
    for suffix in ("/tushare/pro", "/tushare"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break
    return f"{root}/tushare/capabilities"


PROMAX_CAPABILITIES_URL: str = os.environ.get(
    "PROMAX_CAPABILITIES_URL", _promax_capabilities_url(PROMAX_BASE_URL)
)

# 独立密钥，仅后端环境变量/.env；分别绑定对应主机，不跨主机透传
DATAHUBCO_API_KEY: str = os.environ.get("DATAHUBCO_API_KEY", "")
PROMAX_API_KEY: str = os.environ.get("PROMAX_API_KEY", "")

# 基础版当前为明文 HTTP（手册 §2），必须显式允许才启用
DATAHUBCO_ALLOW_HTTP: bool = os.environ.get(
    "DATAHUBCO_ALLOW_HTTP", "false"
).strip().lower() in ("1", "true", "yes")

# TLS: 默认校验，可配置可信 CA 文件（不用示例 verify=False 作为常规配置）
STOCK_TLS_VERIFY: bool = os.environ.get("STOCK_TLS_VERIFY", "true").strip().lower() in (
    "1", "true", "yes"
)
STOCK_CA_FILE: str = os.environ.get("STOCK_CA_FILE", "")

# 代理: 默认信任环境（httpx trust_env）；必要时对股票客户端单独禁用，不改全进程 NO_PROXY
STOCK_HTTP_TRUST_ENV: bool = os.environ.get(
    "STOCK_HTTP_TRUST_ENV", "true"
).strip().lower() in ("1", "true", "yes")

# 超时与重试（design.md §4.1.6）
STOCK_HTTP_CONNECT_TIMEOUT: float = float(os.environ.get("STOCK_HTTP_CONNECT_TIMEOUT", "5"))
DATAHUBCO_READ_TIMEOUT: float = float(os.environ.get("DATAHUBCO_READ_TIMEOUT", "15"))
PROMAX_READ_TIMEOUT: float = float(os.environ.get("PROMAX_READ_TIMEOUT", "30"))
STOCK_REQUEST_DEADLINE: float = float(os.environ.get("STOCK_REQUEST_DEADLINE", "60"))
STOCK_MAX_RETRIES: int = int(os.environ.get("STOCK_MAX_RETRIES", "2"))

# 客户端侧保守预算（不是供应商保证）
STOCK_MAX_CONCURRENCY: int = int(os.environ.get("STOCK_MAX_CONCURRENCY", "4"))
PROMAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("PROMAX_REQUESTS_PER_MINUTE", "120"))

# 旧缓存回退上限（秒，自 fetched_at 计）
STOCK_STALE_MAX_AGE: float = float(os.environ.get("STOCK_STALE_MAX_AGE", str(72 * 3600)))

# ---------------------------------------------------------------------------
# LLM / AI 分析（design.md §4.4、§8.2，阶段8）
# 优先级: SQLite config 表 > 环境变量 > backend/.env > 默认值（逐字段，见 services/llm_config.py）
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "none")
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
LLM_API_BASE: str = os.environ.get("LLM_API_BASE", "")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "")

# LLM 请求预算: 报告整体目标 <15s（design §11.1），单次调用读超时可配置
LLM_CONNECT_TIMEOUT: float = float(os.environ.get("LLM_CONNECT_TIMEOUT", "5"))
LLM_READ_TIMEOUT: float = float(os.environ.get("LLM_READ_TIMEOUT", "45"))
LLM_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "1600"))
LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
LLM_HTTP_TRUST_ENV: bool = os.environ.get(
    "LLM_HTTP_TRUST_ENV", "true"
).strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# 生产部署: FastAPI 托管前端静态文件（design.md §9.2，阶段8）
# ---------------------------------------------------------------------------

FRONTEND_DIST: Path = Path(os.environ.get(
    "STOCKPANEL_FRONTEND_DIST", str(BACKEND_DIR.parent / "frontend" / "dist")))

# 显式开关；未设置时 dist/index.html 存在即自动启用
_SERVE_STATIC_ENV = os.environ.get("STOCKPANEL_SERVE_STATIC", "").strip().lower()
SERVE_STATIC: bool = (
    _SERVE_STATIC_ENV in ("1", "true", "yes") if _SERVE_STATIC_ENV
    else (FRONTEND_DIST / "index.html").is_file()
)


def ensure_dirs() -> None:
    """创建数据目录、缓存目录（启动时调用）。"""
    for d in [DATA_DIR, CACHE_DIR, LOG_DIR, *[CACHE_DIR / v for v in CACHE_SUBDIRS.values()]]:
        d.mkdir(parents=True, exist_ok=True)


def data_source_config_status() -> dict:
    """数据源配置状态（布尔/非敏感，供 /api/config/data-source-status 使用，不回显密钥）。"""
    return {
        "mode": STOCK_DATA_MODE,
        "providers": {
            "datahubco": {
                "configured": bool(DATAHUBCO_API_KEY),
                "base_url": DATAHUBCO_BASE_URL,
                "transport_http": DATAHUBCO_BASE_URL.startswith("http://"),
                "allow_http": DATAHUBCO_ALLOW_HTTP,
            },
            "promax": {
                "configured": bool(PROMAX_API_KEY),
                "base_url": PROMAX_BASE_URL,
                "transport_http": PROMAX_BASE_URL.startswith("http://"),
            },
        },
    }
