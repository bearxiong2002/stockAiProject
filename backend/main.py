"""FastAPI 入口。

- CORS 中间件（允许 localhost）
- 生命周期事件: startup 初始化数据库/加载 LLM 配置，shutdown 清理连接
- GET /api/health 健康检查
- 生产模式: frontend/dist 存在时托管前端静态文件（SPA 回退 index.html，design §9.2）
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from config import settings
from models.database import init_db, close_db
from models.schemas import HealthResponse
from services.providers.errors import DataSourceError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class SPAStaticFiles(StaticFiles):
    """静态文件 + SPA 回退: 未命中的前端路由返回 index.html；/api 路径不吞。

    构建产物缺失时返回 404；不缓存 index.html（避免发版后客户端拿到旧壳）。
    """

    async def get_response(self, path: str, scope) -> Response:
        if path.startswith("api/") or path == "api":
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)
        if path in ("index.html", "."):
            response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    from services.llm_config import load_llm_config
    await load_llm_config()
    logging.getLogger("stockpanel").info(
        "backend started, db=%s (%s), static=%s",
        settings.db_description(),
        "mysql" if settings.is_mysql() else "sqlite",
        settings.SERVE_STATIC and (settings.FRONTEND_DIST / "index.html").is_file(),
    )
    yield
    from services.data_fetcher import get_data_fetcher
    get_data_fetcher().close()   # 释放 httpx 连接池（含懒加载未触发的场景）
    await close_db()
    logging.getLogger("stockpanel").info("backend stopped")


app = FastAPI(title="StockPanel Backend", version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地单用户应用
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康检查（进程健康语义，不探测上游数据源）"""
    return HealthResponse(status="ok", version=settings.APP_VERSION)


@app.exception_handler(DataSourceError)
async def data_source_error_handler(request, exc: DataSourceError):
    """统一数据源错误映射（design.md §4.1.6）。

    配置/权限/能力不可用 → 503；参数 → 400；上游协议 → 502；
    总超时 → 504；限流 → 429。脱敏错误对象，不回显密钥。
    """
    return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()})


# API 路由
from api import collect as collect_api  # noqa: E402
from api import config as config_api  # noqa: E402
from api import market as market_api  # noqa: E402
from api import portfolio as portfolio_api  # noqa: E402
from api import stock as stock_api  # noqa: E402
from api import watchlist as watchlist_api  # noqa: E402

app.include_router(stock_api.router)
app.include_router(config_api.router)
app.include_router(collect_api.router)
app.include_router(portfolio_api.router)
app.include_router(watchlist_api.router)
app.include_router(market_api.router)

# 生产模式: 托管前端构建产物（必须在所有 API 路由之后挂载）
if settings.SERVE_STATIC and (settings.FRONTEND_DIST / "index.html").is_file():
    app.mount("/", SPAStaticFiles(directory=settings.FRONTEND_DIST, html=True),
              name="frontend")
