"""分钟级K线数据采集服务。

按月分窗调用 ProMax pro_bar 拉取分钟K线，批量写入 kline_minute 表。
采集任务以内存 dict 跟踪进度（进程级单例），前端轮询 /collect/status 获取状态；
进程重启后任务进度丢失（幂等：重跑自动跳过已入库数据）。

入库策略: 先查后插——按唯一约束 (stock_code, freq, trade_time) 过滤已存在行后
批量 add_all，兼容 MySQL/SQLite。trade_time 入库前归一化为
"YYYY-MM-DD HH:MM:00"，保证范围判断与查重稳定。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select

from config import settings
from models.database import KlineMinute, get_session_factory
from services.data_fetcher import get_data_fetcher, ts_code_of

logger = logging.getLogger("stockpanel.collector")

_CST = timezone(timedelta(hours=8))


@dataclass
class CollectTaskState:
    stock_code: str
    stock_name: str
    freq: str
    years: int
    status: Literal["collecting", "completed", "error"] = "collecting"
    progress: int = 0          # 0-100
    message: str = "准备中..."
    total_months: int = 0
    fetched_months: int = 0
    total_rows: int = 0
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


# 进程级单例：stock_code -> task state
_tasks: dict[str, CollectTaskState] = {}
# create_task 强引用，防止后台任务被 GC
_async_tasks: set[asyncio.Task] = set()
_lock = threading.Lock()


def _month_windows(years: int) -> list[tuple[str, str]]:
    """生成从 (今天 - years年) 到今天的月度窗口列表。

    返回 [(start_yyyymmdd, end_yyyymmdd), ...] 按时间升序；首尾为不完整月份。
    """
    now = datetime.now(_CST)
    end_date = now
    start_date = now - timedelta(days=years * 365)

    windows: list[tuple[str, str]] = []
    cursor = start_date.replace(day=1)
    while cursor < end_date:
        # 当月最后一天
        if cursor.month == 12:
            month_end = cursor.replace(year=cursor.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = cursor.replace(month=cursor.month + 1, day=1) - timedelta(days=1)
        # 不超过今天
        if month_end > end_date:
            month_end = end_date
        win_start = max(cursor, start_date)
        windows.append((win_start.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")))
        # 下一个月
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return windows


def _normalize_trade_time(raw) -> str:
    """上游分钟线时间 → 'YYYY-MM-DD HH:MM:00'；无法解析时原样返回。"""
    s = str(raw).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y%m%d%H%M", "%Y%m%d%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:00")
        except ValueError:
            continue
    return s


def _date_part(trade_time: str) -> str | None:
    """'2026-09-19 14:35:00' → '20260919'；非规整格式返回 None。"""
    if len(trade_time) >= 10 and trade_time[4] == "-" and trade_time[7] == "-":
        d = trade_time[:10].replace("-", "")
        return d if d.isdigit() else None
    return None


async def _get_existing_range(stock_code: str, freq: str) -> tuple[str | None, str | None]:
    """查询数据库中已有数据的时间范围。返回 (min_trade_time, max_trade_time) 或 (None, None)。"""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(
                func.min(KlineMinute.trade_time),
                func.max(KlineMinute.trade_time),
            ).where(
                KlineMinute.stock_code == stock_code,
                KlineMinute.freq == freq,
            )
        )
        row = result.one()
        return (row[0], row[1])


async def _count_existing(stock_code: str, freq: str) -> int:
    """查询已有数据行数。"""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(func.count()).where(
                KlineMinute.stock_code == stock_code,
                KlineMinute.freq == freq,
            )
        )
        return result.scalar() or 0


async def _fetch_and_store_month(
    stock_code: str, ts_code: str, freq: str,
    start_date: str, end_date: str
) -> int:
    """拉取一个月窗口的分钟K线数据并写入数据库。返回新插入行数。"""
    fetcher = get_data_fetcher()
    # pro_bar 是同步方法（内含限流/重试），放到线程池执行
    result = await asyncio.to_thread(
        fetcher._pm.pro_bar,
        ts_code,
        freq=freq,
        asset="E",
        adj=None,
        start_date=start_date,
        end_date=end_date,
    )

    if not result.rows:
        return 0

    field_idx = {f: i for i, f in enumerate(result.fields)}
    time_idx = next(
        (field_idx[k] for k in ("trade_time", "datetime", "trade_date") if k in field_idx),
        None)
    if time_idx is None:
        raise ValueError(f"pro_bar 返回缺少时间字段: {result.fields}")

    # 批内按 trade_time 去重（上游偶发重复行）
    normalized: dict[str, KlineMinute] = {}
    for row in result.rows:
        t = _normalize_trade_time(row[time_idx])
        if t in normalized:
            continue
        normalized[t] = KlineMinute(
            stock_code=stock_code,
            freq=freq,
            trade_time=t,
            open=_safe_float(row, field_idx, "open"),
            high=_safe_float(row, field_idx, "high"),
            low=_safe_float(row, field_idx, "low"),
            close=_safe_float(row, field_idx, "close"),
            vol=_safe_float(row, field_idx, "vol"),
            amount=_safe_float(row, field_idx, "amount"),
        )
    if not normalized:
        return 0

    # 先查后插：过滤唯一约束 (stock_code, freq, trade_time) 已存在的行
    async with get_session_factory()() as session:
        existing = set((await session.execute(
            select(KlineMinute.trade_time).where(
                KlineMinute.stock_code == stock_code,
                KlineMinute.freq == freq,
                KlineMinute.trade_time.in_(list(normalized)),
            )
        )).scalars().all())
        new_rows = [r for t, r in normalized.items() if t not in existing]
        if new_rows:
            session.add_all(new_rows)
            await session.commit()
    return len(new_rows)


def _safe_float(row: list, field_idx: dict, name: str) -> float | None:
    idx = field_idx.get(name)
    if idx is None:
        return None
    val = row[idx]
    if val is None or val != val:  # None or NaN
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def _run_collect(state: CollectTaskState) -> None:
    """执行采集任务（在 asyncio 后台运行）。"""
    try:
        # mock 模式约定离线运行，不悄悄打真实网络
        if settings.STOCK_DATA_MODE == "mock":
            raise RuntimeError("当前为 mock 数据源模式，分钟线采集需要真实数据源（设置 → 数据源）")

        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)  # 无法识别的代码在此抛 ValueError
        freq = state.freq

        # 生成月度窗口
        windows = _month_windows(state.years)
        state.total_months = len(windows)

        # 检查已有数据范围，跳过已完整覆盖的月份
        existing_min, existing_max = await _get_existing_range(stock_code, freq)
        if existing_min and existing_max:
            min_d, max_d = _date_part(existing_min), _date_part(existing_max)
            if min_d and max_d:
                filtered = [(ws, we) for ws, we in windows
                            if not (ws >= min_d and we <= max_d)]
                if not filtered:
                    state.total_rows = await _count_existing(stock_code, freq)
                    state.progress = 100
                    state.status = "completed"
                    state.message = f"数据已完整（{state.total_rows} 条）"
                    state.finished_at = time.time()
                    return
                windows = filtered
                state.total_months = len(windows)

        state.message = f"开始采集 {state.total_months} 个月的{freq}数据..."

        failed = 0
        last_error: str | None = None
        for i, (ws, we) in enumerate(windows):
            state.fetched_months = i
            state.progress = int((i / state.total_months) * 95)  # 留 5% 给收尾
            state.message = f"正在采集 {ws[:4]}-{ws[4:6]} ({i + 1}/{state.total_months})"

            try:
                count = await _fetch_and_store_month(stock_code, ts_code, freq, ws, we)
                state.total_rows += count
            except Exception as exc:
                # 单月失败不中断整体，记录警告继续
                failed += 1
                last_error = str(exc)
                logger.warning("采集 %s %s 窗口 %s~%s 失败: %s",
                               stock_code, freq, ws, we, exc)

        state.progress = 100
        state.fetched_months = state.total_months
        if failed and state.total_rows == 0:
            # 全部失败视为任务失败，不伪装成功
            state.status = "error"
            state.error = last_error
            state.message = f"采集失败（{failed}/{state.total_months} 个月无数据）: {last_error}"
        else:
            state.status = "completed"
            # 展示库中总量更直观（重复采集/补缺时本次新增可能为 0）
            db_total = await _count_existing(stock_code, freq)
            state.message = f"采集完成，新增 {state.total_rows} 条，库中共 {db_total} 条"
            if failed:
                state.message += f"，{failed} 个月失败"
        state.finished_at = time.time()
        logger.info("采集结束: %s %s, %d 条, 失败月 %d", stock_code, freq,
                    state.total_rows, failed)

    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = f"采集失败: {exc}"
        state.finished_at = time.time()
        logger.error("采集失败 %s: %s", state.stock_code, exc, exc_info=True)


class KlineCollector:
    """分钟级K线采集管理器（进程级单例）。"""

    def start(self, stock_code: str, stock_name: str,
              years: int = 3, freq: str = "5min") -> CollectTaskState:
        """启动采集任务。如果该股票已在采集中，返回现有状态。"""
        with _lock:
            existing = _tasks.get(stock_code)
            if existing and existing.status == "collecting":
                return existing  # 已在采集中

            state = CollectTaskState(
                stock_code=stock_code,
                stock_name=stock_name,
                freq=freq,
                years=years,
            )
            _tasks[stock_code] = state

        # 在 asyncio 事件循环中启动后台任务（API 处理器内调用，必有运行中的 loop）
        task = asyncio.create_task(_run_collect(state))
        _async_tasks.add(task)
        task.add_done_callback(_async_tasks.discard)
        return state

    def get_status(self, stock_code: str) -> CollectTaskState | None:
        """获取采集任务状态。"""
        return _tasks.get(stock_code)

    async def check_data(self, stock_code: str, freq: str = "5min") -> dict:
        """检查数据库中已有的分钟线数据情况。"""
        count = await _count_existing(stock_code, freq)
        min_t, max_t = await _get_existing_range(stock_code, freq)
        return {
            "stock_code": stock_code,
            "freq": freq,
            "exists": count > 0,
            "row_count": count,
            "min_time": min_t,
            "max_time": max_t,
        }


# 进程级单例
_collector: KlineCollector | None = None


def get_collector() -> KlineCollector:
    global _collector
    if _collector is None:
        _collector = KlineCollector()
    return _collector
