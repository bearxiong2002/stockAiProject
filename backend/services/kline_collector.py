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

import pandas as pd
from sqlalchemy import func, select

from config import settings
from models.database import KlineDaily, KlineMinute, get_session_factory
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


def _week_windows(start_date: datetime, end_date: datetime) -> list[tuple[str, str]]:
    """生成周窗口列表（每窗口7天）。5min 线每周约 240 条，低于上游 500 条限制。"""
    windows: list[tuple[str, str]] = []
    cursor = start_date
    while cursor < end_date:
        win_end = min(cursor + timedelta(days=6), end_date)
        windows.append((cursor.strftime("%Y%m%d"), win_end.strftime("%Y%m%d")))
        cursor = win_end + timedelta(days=1)
    return windows


def _month_windows(start_date: datetime, end_date: datetime) -> list[tuple[str, str]]:
    """生成月窗口列表。15min 线每月约 352 条，低于上游 500 条限制。"""
    windows: list[tuple[str, str]] = []
    cursor = start_date
    while cursor < end_date:
        if cursor.month == 12:
            next_month = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            next_month = cursor.replace(month=cursor.month + 1, day=1)
        win_end = min(next_month - timedelta(days=1), end_date)
        windows.append((cursor.strftime("%Y%m%d"), win_end.strftime("%Y%m%d")))
        cursor = next_month
    return windows


def _collect_windows(years: int, freq: str = "15min") -> list[tuple[str, str]]:
    """按 freq 选择合适的窗口大小。15min 用月窗口，5min 用周窗口。"""
    now = datetime.now(_CST)
    start = now - timedelta(days=years * 365)
    if freq in ("1min", "5min"):
        return _week_windows(start, now)
    return _month_windows(start, now)


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


# ---- 日线辅助 ----

async def _get_daily_range(stock_code: str) -> tuple[str | None, str | None]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(
                func.min(KlineDaily.trade_date),
                func.max(KlineDaily.trade_date),
            ).where(KlineDaily.stock_code == stock_code)
        )
        row = result.one()
        return (row[0], row[1])


async def _count_daily(stock_code: str) -> int:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(func.count()).where(KlineDaily.stock_code == stock_code)
        )
        return result.scalar() or 0


async def _fetch_and_store_daily(
    stock_code: str, ts_code: str, start_date: str, end_date: str
) -> int:
    """调用 ProMax daily() 拉取日线并写入 kline_daily 表。返回新插入行数。"""
    fetcher = get_data_fetcher()
    result = await asyncio.to_thread(
        fetcher._pm.daily, ts_code,
        start_date=start_date, end_date=end_date,
    )
    if not result.rows:
        return 0

    field_idx = {f: i for i, f in enumerate(result.fields)}
    td_idx = field_idx.get("trade_date")
    if td_idx is None:
        raise ValueError(f"daily 返回缺少 trade_date: {result.fields}")

    normalized: dict[str, KlineDaily] = {}
    for row in result.rows:
        td = str(row[td_idx]).strip()
        if td in normalized:
            continue
        normalized[td] = KlineDaily(
            stock_code=stock_code,
            trade_date=td,
            open=_safe_float(row, field_idx, "open"),
            high=_safe_float(row, field_idx, "high"),
            low=_safe_float(row, field_idx, "low"),
            close=_safe_float(row, field_idx, "close"),
            pre_close=_safe_float(row, field_idx, "pre_close"),
            change=_safe_float(row, field_idx, "change"),
            pct_chg=_safe_float(row, field_idx, "pct_chg"),
            vol=_safe_float(row, field_idx, "vol"),
            amount=_safe_float(row, field_idx, "amount"),
        )
    if not normalized:
        return 0

    async with get_session_factory()() as session:
        existing = set((await session.execute(
            select(KlineDaily.trade_date).where(
                KlineDaily.stock_code == stock_code,
                KlineDaily.trade_date.in_(list(normalized)),
            )
        )).scalars().all())
        new_rows = [r for t, r in normalized.items() if t not in existing]
        if new_rows:
            session.add_all(new_rows)
            await session.commit()
    return len(new_rows)


def _pro_bar_no_retry(pm, ts_code: str, freq: str, start_date: str, end_date: str):
    """调用 pro_bar 但通过 tight deadline 禁止内部重试，避免 503 时连发 3 次请求。"""
    params = pm.formal_params("pro_bar", {
        "ts_code": ts_code, "freq": freq, "asset": "E",
        "start_date": start_date, "end_date": end_date,
    })
    return pm.get_rows("pro_bar", params, deadline=time.monotonic() + 30)


async def _fetch_and_store_month(
    stock_code: str, ts_code: str, freq: str,
    start_date: str, end_date: str
) -> int:
    """拉取一个窗口的分钟K线数据并写入数据库。返回新插入行数。"""
    fetcher = get_data_fetcher()
    result = await asyncio.to_thread(
        _pro_bar_no_retry,
        fetcher._pm,
        ts_code,
        freq,
        start_date,
        end_date,
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


_FETCH_INTERVAL = 20.0          # 基础请求间隔（秒）— ProMax 约允许 2-3 req/min
_RETRY_INTERVAL = 25.0          # 失败重跑队列的请求间隔（秒）
_RETRY_COOLDOWN = 45.0          # 重跑前的冷却等待（秒）
_MAX_RETRY_ROUNDS = 3           # 最多重跑轮数


async def _fetch_windows(
    state: CollectTaskState,
    stock_code: str, ts_code: str, freq: str,
    windows: list[tuple[str, str]],
    label: str = "采集",
) -> tuple[int, int, str | None]:
    """通用窗口采集循环：首轮采集 + 失败队列重跑。
    返回 (总新增行数, 最终失败数, 最后错误信息)。
    """
    total_count = len(windows)
    state.total_months = total_count
    new_rows = 0
    retry_queue: list[tuple[str, str]] = []
    consecutive_fails = 0
    last_error: str | None = None

    for i, (ws, we) in enumerate(windows):
        state.fetched_months = i
        state.progress = int((i / total_count) * 90)
        state.message = f"{label} {ws[:4]}-{ws[4:6]}-{ws[6:]} ({i + 1}/{total_count})"
        try:
            count = await _fetch_and_store_month(stock_code, ts_code, freq, ws, we)
            new_rows += count
            consecutive_fails = 0
        except Exception as exc:
            consecutive_fails += 1
            last_error = str(exc)
            retry_queue.append((ws, we))
            logger.warning("%s %s 窗口 %s~%s 失败: %s", label, stock_code, ws, we, exc)
            if consecutive_fails >= 3 and "503" in str(exc):
                cooldown = min(30 * consecutive_fails, 120)
                state.message = f"上游限流，冷却 {cooldown}s..."
                logger.info("连续 %d 次 503，冷却 %ds", consecutive_fails, cooldown)
                await asyncio.sleep(cooldown)
        if i < len(windows) - 1:
            await asyncio.sleep(_FETCH_INTERVAL)

    for round_num in range(1, _MAX_RETRY_ROUNDS + 1):
        if not retry_queue:
            break
        logger.info("第 %d 轮重跑 %d 个失败窗口，冷却 %ds...",
                    round_num, len(retry_queue), int(_RETRY_COOLDOWN))
        state.message = f"冷却 {int(_RETRY_COOLDOWN)}s 后重跑 {len(retry_queue)} 个失败窗口..."
        await asyncio.sleep(_RETRY_COOLDOWN)

        still_failed: list[tuple[str, str]] = []
        for j, (ws, we) in enumerate(retry_queue):
            state.progress = 90 + int(((j + 1) / len(retry_queue)) * 10 * round_num / _MAX_RETRY_ROUNDS)
            state.message = f"重跑({round_num}) {ws[:4]}-{ws[4:6]}-{ws[6:]} ({j + 1}/{len(retry_queue)})"
            try:
                count = await _fetch_and_store_month(stock_code, ts_code, freq, ws, we)
                new_rows += count
            except Exception as exc:
                still_failed.append((ws, we))
                last_error = str(exc)
                logger.warning("重跑 %s 窗口 %s~%s 仍失败: %s", stock_code, ws, we, exc)
            if j < len(retry_queue) - 1:
                await asyncio.sleep(_RETRY_INTERVAL)
        retry_queue = still_failed

    final_failed = len(retry_queue)
    state.total_rows = new_rows
    return new_rows, final_failed, last_error


async def _run_collect(state: CollectTaskState) -> None:
    """执行采集任务（在 asyncio 后台运行）。"""
    try:
        if settings.STOCK_DATA_MODE == "mock":
            raise RuntimeError("当前为 mock 数据源模式，分钟线采集需要真实数据源（设置 → 数据源）")

        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)
        freq = state.freq

        windows = _collect_windows(state.years, freq)
        state.total_months = len(windows)

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

        state.message = f"开始采集 {state.total_months} 个窗口的{freq}数据..."
        new_rows, final_failed, last_error = await _fetch_windows(
            state, stock_code, ts_code, freq, windows, label="采集")

        state.progress = 100
        state.fetched_months = state.total_months
        if final_failed and new_rows == 0:
            state.status = "error"
            state.error = last_error
            state.message = f"采集失败（全部 {final_failed} 个窗口无数据）: {last_error}"
        else:
            state.status = "completed"
            db_total = await _count_existing(stock_code, freq)
            state.message = f"采集完成，新增 {new_rows} 条，库中共 {db_total} 条"
            if final_failed:
                state.message += f"，{final_failed} 个窗口仍失败"
        state.finished_at = time.time()
        logger.info("采集结束: %s %s, %d 条, 失败 %d", stock_code, freq,
                    new_rows, final_failed)

    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = f"采集失败: {exc}"
        state.finished_at = time.time()
        logger.error("采集失败 %s: %s", state.stock_code, exc, exc_info=True)


async def _run_update(state: CollectTaskState) -> None:
    """增量采集：从数据库中最新记录到今天。"""
    try:
        if settings.STOCK_DATA_MODE == "mock":
            raise RuntimeError("当前为 mock 数据源模式，分钟线采集需要真实数据源")

        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)
        freq = state.freq

        existing_min, existing_max = await _get_existing_range(stock_code, freq)
        if not existing_max:
            state.status = "error"
            state.error = "无已有数据，请先完整采集"
            state.message = "无已有数据，请先完整采集"
            state.finished_at = time.time()
            return

        max_d = _date_part(existing_max)
        if not max_d:
            state.status = "error"
            state.error = "无法解析已有数据日期"
            state.message = "无法解析已有数据日期"
            state.finished_at = time.time()
            return

        start = datetime.strptime(max_d, "%Y%m%d").replace(tzinfo=_CST) + timedelta(days=1)
        end = datetime.now(_CST)
        if start >= end:
            state.total_rows = await _count_existing(stock_code, freq)
            state.progress = 100
            state.status = "completed"
            state.message = f"已是最新（{state.total_rows} 条）"
            state.finished_at = time.time()
            return

        if freq in ("1min", "5min"):
            windows = _week_windows(start, end)
        else:
            windows = _month_windows(start, end)
        state.total_months = len(windows)
        state.message = f"增量更新 {len(windows)} 个窗口..."

        new_rows, final_failed, _ = await _fetch_windows(
            state, stock_code, ts_code, freq, windows, label="更新")

        state.progress = 100
        state.fetched_months = state.total_months
        db_total = await _count_existing(stock_code, freq)
        state.status = "completed"
        state.message = f"更新完成，新增 {new_rows} 条，共 {db_total} 条"
        if final_failed:
            state.message += f"，{final_failed} 个窗口仍失败"
        state.finished_at = time.time()

    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = f"更新失败: {exc}"
        state.finished_at = time.time()
        logger.error("增量更新失败 %s: %s", state.stock_code, exc, exc_info=True)


def _year_windows(start_date: datetime, end_date: datetime) -> list[tuple[str, str]]:
    """生成按年分割的窗口列表（每窗口 ≤ 365 天，适配 ProMax 366 天限制）。"""
    windows: list[tuple[str, str]] = []
    cursor = start_date
    while cursor < end_date:
        win_end = min(cursor + timedelta(days=364), end_date)
        windows.append((cursor.strftime("%Y%m%d"), win_end.strftime("%Y%m%d")))
        cursor = win_end + timedelta(days=1)
    return windows


async def _run_collect_daily(state: CollectTaskState) -> None:
    """采集日线数据（按年分窗，每窗口一次 API 调用）。"""
    try:
        if settings.STOCK_DATA_MODE == "mock":
            raise RuntimeError("当前为 mock 数据源模式，日线采集需要真实数据源")

        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)

        now = datetime.now(_CST)
        start = now - timedelta(days=state.years * 365)
        end_str = now.strftime("%Y%m%d")

        existing_count = await _count_daily(stock_code)
        if existing_count > 0:
            _, existing_max = await _get_daily_range(stock_code)
            if existing_max and existing_max >= end_str:
                state.total_rows = existing_count
                state.progress = 100
                state.status = "completed"
                state.message = f"数据已完整（{existing_count} 条）"
                state.finished_at = time.time()
                return

        windows = _year_windows(start, now)
        total_new = 0
        for i, (ws, we) in enumerate(windows):
            state.progress = int((i / len(windows)) * 90)
            state.message = f"采集日线 {ws[:4]}-{ws[4:6]}~{we[:4]}-{we[4:6]} ({i + 1}/{len(windows)})"
            new_rows = await _fetch_and_store_daily(stock_code, ts_code, ws, we)
            total_new += new_rows
            if i < len(windows) - 1:
                await asyncio.sleep(3)

        state.progress = 100
        db_total = await _count_daily(stock_code)
        state.total_rows = db_total
        state.status = "completed"
        state.message = f"采集完成，新增 {total_new} 条，共 {db_total} 条"
        state.finished_at = time.time()
        logger.info("日线采集完成: %s, 新增 %d, 共 %d", stock_code, total_new, db_total)

    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = f"采集失败: {exc}"
        state.finished_at = time.time()
        logger.error("日线采集失败 %s: %s", state.stock_code, exc, exc_info=True)


async def _run_update_daily(state: CollectTaskState) -> None:
    """增量更新日线数据：从 max(trade_date)+1 到今天。"""
    try:
        if settings.STOCK_DATA_MODE == "mock":
            raise RuntimeError("当前为 mock 数据源模式")

        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)

        _, existing_max = await _get_daily_range(stock_code)
        if not existing_max:
            state.status = "error"
            state.error = "无已有数据，请先完整采集"
            state.message = "无已有数据，请先完整采集"
            state.finished_at = time.time()
            return

        start_dt = datetime.strptime(existing_max, "%Y%m%d") + timedelta(days=1)
        end_dt = datetime.now(_CST)
        if start_dt.date() > end_dt.date():
            db_total = await _count_daily(stock_code)
            state.total_rows = db_total
            state.progress = 100
            state.status = "completed"
            state.message = f"已是最新（{db_total} 条）"
            state.finished_at = time.time()
            return

        state.message = "增量更新日线..."
        state.progress = 30

        new_rows = await _fetch_and_store_daily(
            stock_code, ts_code,
            start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"),
        )

        db_total = await _count_daily(stock_code)
        state.total_rows = db_total
        state.progress = 100
        state.status = "completed"
        state.message = f"更新完成，新增 {new_rows} 条，共 {db_total} 条"
        state.finished_at = time.time()

    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = f"更新失败: {exc}"
        state.finished_at = time.time()
        logger.error("日线增量更新失败 %s: %s", state.stock_code, exc, exc_info=True)


# ---- 本地 K 线读取（日线 → 周线/月线聚合）----

def _yyyymmdd_to_iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


async def get_local_kline(
    stock_code: str, period: str = "daily",
    start_date: str | None = None, end_date: str | None = None,
) -> list[dict] | None:
    """从本地 DB 读取日线并按 period 聚合。无数据返回 None。"""
    sd = start_date.replace("-", "") if start_date else None
    ed = end_date.replace("-", "") if end_date else None

    async with get_session_factory()() as session:
        query = (
            select(KlineDaily)
            .where(KlineDaily.stock_code == stock_code)
        )
        if sd:
            query = query.where(KlineDaily.trade_date >= sd)
        if ed:
            query = query.where(KlineDaily.trade_date <= ed)
        query = query.order_by(KlineDaily.trade_date)
        result = await session.execute(query)
        rows = result.scalars().all()

    if not rows:
        return None

    items = []
    for r in rows:
        pre = r.pre_close or 0
        vol = r.vol
        amt = r.amount
        items.append({
            "date": _yyyymmdd_to_iso(r.trade_date),
            "open": round(r.open, 4) if r.open is not None else None,
            "close": round(r.close, 4) if r.close is not None else None,
            "high": round(r.high, 4) if r.high is not None else None,
            "low": round(r.low, 4) if r.low is not None else None,
            "volume": int(vol * 100) if vol is not None else None,
            "amount": round(amt * 1000, 2) if amt is not None else None,
            "amplitude": round((r.high - r.low) / pre * 100, 4)
            if pre and r.high is not None and r.low is not None else None,
            "pct_change": round(r.pct_chg, 4) if r.pct_chg is not None else None,
            "change": round(r.change, 4) if r.change is not None else None,
            "turnover": None,
        })

    if period == "daily":
        return items

    from services.providers.normalize import resample_period
    df = pd.DataFrame(items)
    resampled = resample_period(df, period)
    return resampled.to_dict("records")


class KlineCollector:
    """K线采集管理器（进程级单例），支持分钟线和日线。"""

    def start(self, stock_code: str, stock_name: str,
              years: int = 1, freq: str = "daily") -> CollectTaskState:
        """启动采集任务。如果该股票已在采集中，返回现有状态。"""
        with _lock:
            existing = _tasks.get(stock_code)
            if existing and existing.status == "collecting":
                return existing

            state = CollectTaskState(
                stock_code=stock_code,
                stock_name=stock_name,
                freq=freq,
                years=years,
            )
            _tasks[stock_code] = state

        coro = _run_collect_daily(state) if freq == "daily" else _run_collect(state)
        task = asyncio.create_task(coro)
        _async_tasks.add(task)
        task.add_done_callback(_async_tasks.discard)
        return state

    def get_status(self, stock_code: str) -> CollectTaskState | None:
        """获取采集任务状态。"""
        return _tasks.get(stock_code)

    async def check_data(self, stock_code: str, freq: str = "daily") -> dict:
        """检查数据库中已有数据情况。"""
        if freq == "daily":
            count = await _count_daily(stock_code)
            min_t, max_t = await _get_daily_range(stock_code)
        else:
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

    async def delete_data(self, stock_code: str, freq: str = "daily") -> int:
        """删除指定股票的数据，返回删除行数。"""
        from sqlalchemy import delete
        async with get_session_factory()() as session:
            if freq == "daily":
                result = await session.execute(
                    delete(KlineDaily).where(KlineDaily.stock_code == stock_code)
                )
            else:
                result = await session.execute(
                    delete(KlineMinute).where(
                        KlineMinute.stock_code == stock_code,
                        KlineMinute.freq == freq,
                    )
                )
            await session.commit()
            removed = result.rowcount
        with _lock:
            _tasks.pop(stock_code, None)
        logger.info("已删除 %s %s 数据: %d 条", stock_code, freq, removed)
        return removed

    def start_update(self, stock_code: str, stock_name: str,
                     freq: str = "daily") -> CollectTaskState:
        """增量更新：从数据库最新记录到今天补齐数据。"""
        with _lock:
            existing = _tasks.get(stock_code)
            if existing and existing.status == "collecting":
                return existing

            state = CollectTaskState(
                stock_code=stock_code,
                stock_name=stock_name,
                freq=freq,
                years=0,
            )
            state.message = "增量更新中..."
            _tasks[stock_code] = state

        coro = _run_update_daily(state) if freq == "daily" else _run_update(state)
        task = asyncio.create_task(coro)
        _async_tasks.add(task)
        task.add_done_callback(_async_tasks.discard)
        return state

    async def list_collected(self, page: int = 1, page_size: int = 12) -> dict:
        """列出所有已采集数据的股票，按数据量降序，支持分页。"""
        from sqlalchemy import literal_column, union_all
        async with get_session_factory()() as session:
            daily_q = (
                select(
                    KlineDaily.stock_code,
                    literal_column("'daily'").label("freq"),
                    func.count().label("row_count"),
                    func.min(KlineDaily.trade_date).label("min_time"),
                    func.max(KlineDaily.trade_date).label("max_time"),
                )
                .group_by(KlineDaily.stock_code)
            )
            minute_q = (
                select(
                    KlineMinute.stock_code,
                    KlineMinute.freq,
                    func.count().label("row_count"),
                    func.min(KlineMinute.trade_time).label("min_time"),
                    func.max(KlineMinute.trade_time).label("max_time"),
                )
                .group_by(KlineMinute.stock_code, KlineMinute.freq)
            )
            base = union_all(daily_q, minute_q).subquery()

            total_result = await session.execute(
                select(func.count()).select_from(base)
            )
            total = total_result.scalar() or 0

            rows = await session.execute(
                select(base).order_by(base.c.row_count.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = []
            for r in rows.all():
                stock_name = ""
                task = _tasks.get(r.stock_code)
                if task:
                    stock_name = task.stock_name
                items.append({
                    "stock_code": r.stock_code,
                    "stock_name": stock_name,
                    "freq": r.freq,
                    "row_count": r.row_count,
                    "min_time": r.min_time,
                    "max_time": r.max_time,
                })
        return {"items": items, "total": total, "page": page, "page_size": page_size}


_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def aggregate_daily_kline_sync(stock_code: str, freq: str = "15min") -> pd.DataFrame | None:
    """同步包装，供 ReportBuilder 等同步上下文（工作线程）调用。"""
    loop = _main_loop
    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            aggregate_daily_kline(stock_code, freq), loop
        )
        return future.result(timeout=30)
    return asyncio.run(aggregate_daily_kline(stock_code, freq))


async def aggregate_daily_kline(stock_code: str, freq: str = "15min") -> pd.DataFrame | None:
    """从本地分钟K线聚合出日线 DataFrame，格式对齐 KLINE_COLUMNS。无数据返回 None。"""
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(
                KlineMinute.trade_time,
                KlineMinute.open,
                KlineMinute.high,
                KlineMinute.low,
                KlineMinute.close,
                KlineMinute.vol,
                KlineMinute.amount,
            )
            .where(KlineMinute.stock_code == stock_code, KlineMinute.freq == freq)
            .order_by(KlineMinute.trade_time)
        )
        data = rows.all()
    if not data:
        return None

    df = pd.DataFrame(data, columns=["trade_time", "open", "high", "low", "close", "vol", "amount"])
    df["date"] = df["trade_time"].str[:10]
    for col in ("open", "high", "low", "close", "vol", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    daily = df.groupby("date", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("vol", "sum"),
        amount=("amount", "sum"),
    ).reset_index()

    daily["volume"] = daily["volume"].round().astype("Int64")
    daily["amount"] = daily["amount"].round(2)

    pre_close = daily["close"].shift(1)
    daily["change"] = (daily["close"] - pre_close).round(4)
    daily["pct_change"] = ((daily["change"] / pre_close) * 100).round(4)
    daily["amplitude"] = (((daily["high"] - daily["low"]) / pre_close) * 100).round(4)
    daily["turnover"] = None

    return daily[["date", "open", "close", "high", "low", "volume", "amount",
                  "amplitude", "pct_change", "change", "turnover"]]


# 进程级单例
_collector: KlineCollector | None = None


def get_collector() -> KlineCollector:
    global _collector
    if _collector is None:
        _collector = KlineCollector()
    return _collector
