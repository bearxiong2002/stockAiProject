"""SQLAlchemy 异步引擎 + ORM 模型 + 自动建表。

数据库: 优先 MySQL（backend/.env 中 MYSQL_* 配置，驱动 aiomysql）；
MYSQL_HOST 未配置时回退 SQLite (stockpanel.db，位于系统应用数据目录)。
连接信息（密码/IP/库名）只来自配置，不入日志。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

_CST = timezone(timedelta(hours=8))  # 全系统统一东八区时间戳

from sqlalchemy import String, Text, Float, Integer, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings

logger = logging.getLogger("stockpanel.database")


class Base(DeclarativeBase):
    pass


class Holding(Base):
    """持仓表"""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False)
    buy_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(_CST).isoformat())
    updated_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(_CST).isoformat())


class WatchlistItem(Base):
    """自选股表"""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    added_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(_CST).isoformat())
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ConfigItem(Base):
    """配置表 (key-value)"""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(_CST).isoformat())


class ReportHistory(Base):
    """报告历史"""

    __tablename__ = "report_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(_CST).isoformat())


class KlineMinute(Base):
    """分钟级K线数据（5min/15min/30min/60min）"""

    __tablename__ = "kline_minute"
    __table_args__ = (
        # 防重复采集入库；查询按 stock_code+freq+时间范围
        UniqueConstraint("stock_code", "freq", "trade_time", name="uq_kline_minute"),
        {"mysql_engine": "InnoDB"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    freq: Mapped[str] = mapped_column(String(8), nullable=False, default="5min")
    trade_time: Mapped[str] = mapped_column(String(32), nullable=False)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)


class KlineDaily(Base):
    """日线K线数据"""

    __tablename__ = "kline_daily"
    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_kline_daily"),
        {"mysql_engine": "InnoDB"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(16), nullable=False)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    pre_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_chg: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = settings.database_url()
        if url.startswith("mysql"):
            _engine = create_async_engine(
                url, echo=False, pool_recycle=3600
            )
        else:
            _engine = create_async_engine(url, echo=False)
    return _engine


async def _ensure_mysql_database() -> None:
    """MySQL: 目标库不存在时尝试自动创建（无权限时告警，由后续建表报真实错误）。"""
    url = settings.mysql_url(with_db=False)
    if url is None:
        return
    dbname = settings.MYSQL_DATABASE.replace("`", "")  # 防注入: 标识符转义
    try:
        engine = create_async_engine(url, echo=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"CREATE DATABASE IF NOT EXISTS `{dbname}` "
                    f"CHARACTER SET {settings.MYSQL_CHARSET}"
                ))
        finally:
            await engine.dispose()
        logger.info("MySQL 数据库已就绪: %s", dbname)
    except Exception as exc:
        logger.warning("预建数据库失败（%s: %s），若库已存在可忽略", type(exc).__name__, exc)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """建库建表（幂等）。"""
    settings.ensure_dirs()
    if settings.is_mysql():
        await _ensure_mysql_database()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """释放引擎连接。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
