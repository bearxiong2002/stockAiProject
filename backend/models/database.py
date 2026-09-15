"""SQLAlchemy 异步引擎 + ORM 模型 + 自动建表。

数据库: SQLite (stockpanel.db)，位于系统应用数据目录。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_CST = timezone(timedelta(hours=8))  # 全系统统一东八区时间戳

from sqlalchemy import String, Text, Float, Integer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


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


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(f"sqlite+aiosqlite:///{settings.DB_PATH}", echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """建库建表（幂等）。"""
    settings.ensure_dirs()
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
