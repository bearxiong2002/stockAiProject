# 5分钟K线数据采集 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在股票分析页面增加 5 分钟 K 线数据采集功能——用户点击股票后先采集历史高频数据入库，采集完成后再生成分析报告。

**Architecture:** 后端新增 `KlineMinute` 数据库模型和 `KlineCollector` 服务，通过 ProMax `pro_bar(freq="5min")` 按月分窗拉取数据并批量写入数据库。采集任务以内存 dict 跟踪进度，前端每 2 秒轮询状态接口。前端在 SearchPanel 下方渲染采集卡片，显示进度条和状态，完成后用户点击卡片触发报告生成。

**Tech Stack:** FastAPI / SQLAlchemy async / React / Ant Design / TypeScript

**Spec:** 无独立 spec 文档，设计决策已在对话中确认。

## Global Constraints

- Python 3.13+，前端 React 18 + Ant Design 5
- 数据源调用走 `ProMaxSource.pro_bar`，受限流器 120 次/分保护
- 数据库同时支持 MySQL (aiomysql) 和 SQLite (aiosqlite)，模型用 SQLAlchemy 2.x mapped_column
- 所有时间戳使用东八区 (CST)
- 不引入新依赖

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/models/database.py` | 修改 | 新增 `KlineMinute` ORM 模型 |
| `backend/services/kline_collector.py` | 新建 | 采集任务管理：启动/进度/查重/入库 |
| `backend/api/collect.py` | 新建 | REST 路由：`POST /start`、`GET /status`、`GET /check` |
| `backend/main.py` | 修改 | 注册 collect 路由 |
| `frontend/src/types/index.ts` | 修改 | 新增 `CollectStatus` 类型 |
| `frontend/src/services/api.ts` | 修改 | 新增采集相关 API 函数 |
| `frontend/src/pages/StockAnalysis/CollectCard.tsx` | 新建 | 采集进度卡片组件 |
| `frontend/src/pages/StockAnalysis/SearchPanel.tsx` | 修改 | 集成 CollectCard |
| `frontend/src/pages/StockAnalysis/index.tsx` | 修改 | 采集→报告流程串联 |

---

### Task 1: KlineMinute 数据库模型

**Files:**
- Modify: `backend/models/database.py`

**Interfaces:**
- Produces: `KlineMinute` ORM 类，供 Task 2 的 `KlineCollector` 使用

- [x] **Step 1: 在 `backend/models/database.py` 的 `ReportHistory` 类之后添加 `KlineMinute` 模型**

```python
class KlineMinute(Base):
    """分钟级K线数据（5min/15min/30min/60min）"""

    __tablename__ = "kline_minute"
    __table_args__ = (
        # 防重复插入；查询按 stock_code+freq+时间范围
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
```

注意：还需要在模型上添加唯一约束。在 `__table_args__` 中增加：

```python
from sqlalchemy import UniqueConstraint

__table_args__ = (
    UniqueConstraint("stock_code", "freq", "trade_time", name="uq_kline_minute"),
    {"mysql_engine": "InnoDB"},
)
```

需要在文件顶部的 import 中添加 `UniqueConstraint`：

```python
from sqlalchemy import String, Text, Float, Integer, text, UniqueConstraint
```

- [x] **Step 2: 验证模型注册**

启动后端确认建表成功：

```bash
cd backend && python -c "
import asyncio
from models.database import init_db
asyncio.run(init_db())
print('OK: kline_minute table created')
"
```

- [x] **Step 3: Commit**

```bash
git add backend/models/database.py
git commit -m "feat: add KlineMinute model for minute-level kline storage"
```

---

### Task 2: KlineCollector 采集服务

**Files:**
- Create: `backend/services/kline_collector.py`

**Interfaces:**
- Consumes: `KlineMinute` (from Task 1), `ProMaxSource.pro_bar` (existing), `get_session_factory` (existing)
- Produces: `KlineCollector` 类 — `start_collect(code, years, freq)`, `get_status(code)`, `check_data(code, freq)`

这是核心服务，负责：
1. 管理内存中的任务状态（进度、错误、完成标记）
2. 检查数据库已有数据范围，只采集缺失月份
3. 按月分窗调用 ProMax pro_bar 拉取 5 分钟 K 线
4. 批量写入数据库（每月一批，INSERT IGNORE 防重复）

- [x] **Step 1: 创建 `backend/services/kline_collector.py`**

```python
"""分钟级K线数据采集服务。

按月分窗调用 ProMax pro_bar 拉取 5 分钟 K 线，批量写入 kline_minute 表。
采集任务以内存 dict 跟踪进度（进程级单例），前端轮询 /collect/status 获取状态。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from models.database import KlineMinute, get_session_factory
from services.data_fetcher import get_data_fetcher
from services.providers.normalize import ts_code_of

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
_lock = threading.Lock()


def _month_windows(years: int) -> list[tuple[str, str]]:
    """生成从 (今天 - years年) 到今天的月度窗口列表。
    返回 [(start_yyyymmdd, end_yyyymmdd), ...] 按时间升序。
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


async def _get_existing_range(stock_code: str, freq: str) -> tuple[str | None, str | None]:
    """查询数据库中已有数据的时间范围。返回 (min_trade_time, max_trade_time) 或 (None, None)。"""
    from sqlalchemy import func, select
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
    from sqlalchemy import func, select
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
    # pro_bar 是同步方法，放到线程池执行
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

    # 构建 ORM 对象列表
    fields = result.fields
    rows_to_insert: list[KlineMinute] = []

    # 字段索引映射 — pro_bar 返回字段通常为:
    # ts_code, trade_time, open, high, low, close, vol, amount 等
    field_idx = {f: i for i, f in enumerate(fields)}

    for row in result.rows:
        trade_time = str(row[field_idx.get("trade_time", field_idx.get("datetime", 0))])
        rows_to_insert.append(KlineMinute(
            stock_code=stock_code,
            freq=freq,
            trade_time=trade_time,
            open=_safe_float(row, field_idx, "open"),
            high=_safe_float(row, field_idx, "high"),
            low=_safe_float(row, field_idx, "low"),
            close=_safe_float(row, field_idx, "close"),
            vol=_safe_float(row, field_idx, "vol"),
            amount=_safe_float(row, field_idx, "amount"),
        ))

    if not rows_to_insert:
        return 0

    # 批量插入，跳过已存在的行（ON CONFLICT DO NOTHING 语义）
    inserted = 0
    async with get_session_factory()() as session:
        for item in rows_to_insert:
            try:
                session.add(item)
                await session.flush()
                inserted += 1
            except Exception:
                await session.rollback()
                # 唯一约束冲突 → 跳过（已有此行）
                session = get_session_factory()()
                continue
        await session.commit()
    return inserted


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
        stock_code = state.stock_code
        ts_code = ts_code_of(stock_code)
        freq = state.freq

        # 生成月度窗口
        windows = _month_windows(state.years)
        state.total_months = len(windows)

        # 检查已有数据范围，过滤掉已覆盖的月份
        existing_min, existing_max = await _get_existing_range(stock_code, freq)
        if existing_min and existing_max:
            # 只保留数据库中尚未覆盖的窗口
            # existing 范围 [min, max] 内的月份视为已采集
            filtered: list[tuple[str, str]] = []
            for ws, we in windows:
                if ws >= existing_min[:8].replace("-", "") and we <= existing_max[:8].replace("-", ""):
                    continue  # 此窗口已覆盖
                filtered.append((ws, we))
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

        for i, (ws, we) in enumerate(windows):
            state.fetched_months = i
            state.progress = int((i / state.total_months) * 95)  # 留 5% 给收尾
            month_label = f"{ws[:4]}-{ws[4:6]}"
            state.message = f"正在采集 {month_label} ({i+1}/{state.total_months})"

            try:
                count = await _fetch_and_store_month(stock_code, ts_code, freq, ws, we)
                state.total_rows += count
            except Exception as exc:
                logger.warning("采集 %s %s 窗口 %s~%s 失败: %s",
                               stock_code, freq, ws, we, exc)
                # 单月失败不中断整体，记录警告继续
                continue

        state.progress = 100
        state.status = "completed"
        state.fetched_months = state.total_months
        state.message = f"采集完成，共 {state.total_rows} 条数据"
        state.finished_at = time.time()
        logger.info("采集完成: %s %s, %d 条", stock_code, freq, state.total_rows)

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

        # 在 asyncio 事件循环中启动后台任务
        asyncio.create_task(_run_collect(state))
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
```

**关于 `_fetch_and_store_month` 中批量插入的优化说明：**

上面用了逐行 try/flush 来处理唯一约束冲突。如果使用 MySQL，可以改用更高效的方式：

```python
# MySQL 专用优化（可选，替换逐行插入）:
from sqlalchemy.dialects.mysql import insert as mysql_insert

stmt = mysql_insert(KlineMinute).values([{...}, {...}])
stmt = stmt.on_duplicate_key_update(close=stmt.inserted.close)  # 或 DO NOTHING
await session.execute(stmt)
await session.commit()
```

但为了同时兼容 SQLite，建议先用逐行方式，后续如有性能需求再优化为方言特定写法。

**更好的兼容写法（推荐替换逐行插入部分）：**

```python
# 先查询已有的 trade_time 集合，过滤后批量 add_all
async with get_session_factory()() as session:
    from sqlalchemy import select
    existing_times = set()
    result = await session.execute(
        select(KlineMinute.trade_time).where(
            KlineMinute.stock_code == stock_code,
            KlineMinute.freq == freq,
            KlineMinute.trade_time.in_([r.trade_time for r in rows_to_insert]),
        )
    )
    existing_times = {row[0] for row in result.all()}
    new_rows = [r for r in rows_to_insert if r.trade_time not in existing_times]
    if new_rows:
        session.add_all(new_rows)
        await session.commit()
    inserted = len(new_rows)
```

**选择哪种写法由实现者决定**，两种都可以。推荐后者（先查后插），更高效且兼容 SQLite/MySQL。

- [x] **Step 2: 验证服务模块可导入**

```bash
cd backend && python -c "from services.kline_collector import get_collector; print('OK')"
```

- [x] **Step 3: Commit**

```bash
git add backend/services/kline_collector.py
git commit -m "feat: add KlineCollector service for minute kline data collection"
```

---

### Task 3: 采集 API 路由

**Files:**
- Create: `backend/api/collect.py`
- Modify: `backend/main.py` (添加路由注册)

**Interfaces:**
- Consumes: `KlineCollector.start`, `KlineCollector.get_status`, `KlineCollector.check_data` (from Task 2)
- Produces: REST API 供前端调用 —
  - `POST /api/collect/{code}/start` → `{ status, progress, message, ... }`
  - `GET /api/collect/{code}/status` → `{ status, progress, message, total_rows, ... }`
  - `GET /api/collect/{code}/check` → `{ exists, row_count, min_time, max_time }`

- [x] **Step 1: 创建 `backend/api/collect.py`**

```python
"""分钟K线数据采集路由 /api/collect/*"""
from __future__ import annotations

from fastapi import APIRouter, Query

from services.kline_collector import get_collector

router = APIRouter(prefix="/api/collect", tags=["collect"])

_collector = get_collector()


@router.post("/{code}/start")
async def start_collect(
    code: str,
    name: str = Query("", description="股票名称（前端传入，用于卡片显示）"),
    years: int = Query(3, ge=1, le=10, description="采集年数，默认3年"),
    freq: str = Query("5min", pattern="^(1min|5min|15min|30min|60min)$"),
):
    """启动分钟K线采集任务。已在采集中则返回现有进度。"""
    state = _collector.start(code, name, years=years, freq=freq)
    return _state_to_dict(state)


@router.get("/{code}/status")
async def collect_status(code: str):
    """查询采集任务进度。无任务返回 idle 状态。"""
    state = _collector.get_status(code)
    if state is None:
        return {"stock_code": code, "status": "idle", "progress": 0, "message": "未开始"}
    return _state_to_dict(state)


@router.get("/{code}/check")
async def check_collect(code: str, freq: str = Query("5min")):
    """查询数据库中已有的分钟线数据情况。"""
    return await _collector.check_data(code, freq)


def _state_to_dict(state) -> dict:
    return {
        "stock_code": state.stock_code,
        "stock_name": state.stock_name,
        "freq": state.freq,
        "years": state.years,
        "status": state.status,
        "progress": state.progress,
        "message": state.message,
        "total_months": state.total_months,
        "fetched_months": state.fetched_months,
        "total_rows": state.total_rows,
        "error": state.error,
    }
```

- [x] **Step 2: 在 `backend/main.py` 中注册路由**

在现有的路由导入区域（约第 98-104 行），添加：

```python
from api import collect as collect_api  # noqa: E402
```

在 `app.include_router(market_api.router)` 之后添加：

```python
app.include_router(collect_api.router)
```

- [x] **Step 3: 验证路由可访问**

启动后端后：

```bash
curl -X POST "http://localhost:18900/api/collect/000001/start?name=平安银行&years=3&freq=5min"
curl "http://localhost:18900/api/collect/000001/status"
curl "http://localhost:18900/api/collect/000001/check"
```

- [x] **Step 4: Commit**

```bash
git add backend/api/collect.py backend/main.py
git commit -m "feat: add collect API routes for minute kline data"
```

---

### Task 4: 前端类型和 API 函数

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`

**Interfaces:**
- Produces: `CollectStatus` 类型, `startCollect()`, `getCollectStatus()`, `checkCollectData()` API 函数

- [x] **Step 1: 在 `frontend/src/types/index.ts` 末尾添加采集相关类型**

```typescript
// =====================================================================
// 分钟K线数据采集
// =====================================================================

export interface CollectStatus {
  stock_code: string
  stock_name: string
  freq: string
  years: number
  status: 'idle' | 'collecting' | 'completed' | 'error'
  progress: number
  message: string
  total_months: number
  fetched_months: number
  total_rows: number
  error: string | null
}

export interface CollectCheckResult {
  stock_code: string
  freq: string
  exists: boolean
  row_count: number
  min_time: string | null
  max_time: string | null
}
```

- [x] **Step 2: 在 `frontend/src/services/api.ts` 末尾添加采集 API 函数**

```typescript
// =====================================================================
// 分钟K线数据采集
// =====================================================================

import type { CollectCheckResult, CollectStatus } from '@/types'

export async function startCollect(
  code: string,
  name: string,
  years = 3,
  freq = '5min'
): Promise<CollectStatus> {
  const { data } = await api.post<CollectStatus>(
    `/collect/${code}/start`,
    null,
    { params: { name, years, freq } }
  )
  return data
}

export async function getCollectStatus(code: string): Promise<CollectStatus> {
  const { data } = await api.get<CollectStatus>(`/collect/${code}/status`)
  return data
}

export async function checkCollectData(
  code: string,
  freq = '5min'
): Promise<CollectCheckResult> {
  const { data } = await api.get<CollectCheckResult>(
    `/collect/${code}/check`,
    { params: { freq } }
  )
  return data
}
```

- [x] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat: add collect types and API functions in frontend"
```

---

### Task 5: CollectCard 前端组件

**Files:**
- Create: `frontend/src/pages/StockAnalysis/CollectCard.tsx`

**Interfaces:**
- Consumes: `startCollect`, `getCollectStatus`, `checkCollectData` (from Task 4)
- Produces: `<CollectCard stock={StockBrief} onComplete={(stock) => void} />` 组件

该组件的行为：
1. 挂载时先调 `checkCollectData` 检查是否已有数据
2. 如已有 → 直接显示"数据已就绪"，可点击生成报告
3. 如无数据 → 自动调 `startCollect` 启动采集
4. 采集中 → 每 2 秒轮询 `getCollectStatus`，显示进度条
5. 完成 → 显示"采集完成"，可点击生成报告
6. 错误 → 显示错误信息和重试按钮

- [x] **Step 1: 创建 `frontend/src/pages/StockAnalysis/CollectCard.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Card, Progress, Tag, Typography } from 'antd'
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  LoadingOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { checkCollectData, getCollectStatus, startCollect } from '@/services/api'
import type { CollectStatus, StockBrief } from '@/types'

interface CollectCardProps {
  stock: StockBrief
  years?: number
  freq?: string
  onComplete: (stock: StockBrief) => void
}

export default function CollectCard({
  stock,
  years = 3,
  freq = '5min',
  onComplete,
}: CollectCardProps) {
  const [status, setStatus] = useState<CollectStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const startPolling = useCallback(
    (code: string) => {
      stopPolling()
      timerRef.current = setInterval(async () => {
        try {
          const s = await getCollectStatus(code)
          setStatus(s)
          if (s.status === 'completed' || s.status === 'error') {
            stopPolling()
          }
        } catch {
          // 网络错误忽略，继续轮询
        }
      }, 2000)
    },
    [stopPolling]
  )

  const doStart = useCallback(async () => {
    try {
      const s = await startCollect(stock.code, stock.name ?? '', years, freq)
      setStatus(s)
      if (s.status === 'collecting') {
        startPolling(stock.code)
      }
    } catch (err) {
      setStatus({
        stock_code: stock.code,
        stock_name: stock.name ?? '',
        freq,
        years,
        status: 'error',
        progress: 0,
        message: `启动失败: ${err}`,
        total_months: 0,
        fetched_months: 0,
        total_rows: 0,
        error: String(err),
      })
    }
  }, [stock, years, freq, startPolling])

  // 挂载时：先检查是否已有数据
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        // 先检查是否有正在进行的任务
        const taskStatus = await getCollectStatus(stock.code)
        if (alive && taskStatus.status === 'collecting') {
          setStatus(taskStatus)
          setChecking(false)
          startPolling(stock.code)
          return
        }
        if (alive && taskStatus.status === 'completed') {
          setStatus(taskStatus)
          setChecking(false)
          return
        }
        // 再检查数据库
        const check = await checkCollectData(stock.code, freq)
        if (alive && check.exists && check.row_count > 0) {
          setStatus({
            stock_code: stock.code,
            stock_name: stock.name ?? '',
            freq,
            years,
            status: 'completed',
            progress: 100,
            message: `数据已就绪（${check.row_count.toLocaleString()} 条）`,
            total_months: 0,
            fetched_months: 0,
            total_rows: check.row_count,
            error: null,
          })
          setChecking(false)
          return
        }
        // 无数据，自动启动采集
        if (alive) {
          setChecking(false)
          await doStart()
        }
      } catch {
        if (alive) {
          setChecking(false)
          await doStart()
        }
      }
    })()
    return () => {
      alive = false
      stopPolling()
    }
  }, [stock.code]) // eslint-disable-line react-hooks/exhaustive-deps

  if (checking) {
    return (
      <Card size="small" style={{ marginTop: 16 }}>
        <LoadingOutlined style={{ marginRight: 8 }} />
        检查 {stock.name}（{stock.code}）的历史数据...
      </Card>
    )
  }

  if (!status) return null

  const isCollecting = status.status === 'collecting'
  const isCompleted = status.status === 'completed'
  const isError = status.status === 'error'

  return (
    <Card
      size="small"
      style={{
        marginTop: 16,
        border: isCompleted
          ? '1px solid var(--success-color, #52c41a)'
          : isError
            ? '1px solid var(--error-color, #ff4d4f)'
            : '1px solid var(--border-color)',
        cursor: isCompleted ? 'pointer' : 'default',
      }}
      onClick={isCompleted ? () => onComplete(stock) : undefined}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <DatabaseOutlined style={{ fontSize: 18 }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <strong>{stock.name}</strong>
            <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
              {stock.code}
            </span>
            <Tag color={isCompleted ? 'green' : isError ? 'red' : 'blue'}>
              {freq} · {years}年
            </Tag>
          </div>

          {isCollecting && (
            <div style={{ marginTop: 8 }}>
              <Progress
                percent={status.progress}
                size="small"
                status="active"
                strokeColor="var(--primary)"
              />
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                {status.message}
                {status.total_rows > 0 && ` · 已入库 ${status.total_rows.toLocaleString()} 条`}
              </div>
            </div>
          )}

          {isCompleted && (
            <div style={{ marginTop: 4, fontSize: 12 }}>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
              {status.message}
              <span style={{ color: 'var(--primary)', marginLeft: 8 }}>
                点击生成分析报告 →
              </span>
            </div>
          )}

          {isError && (
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 12, color: '#ff4d4f' }}>
                <WarningOutlined style={{ marginRight: 4 }} />
                {status.message}
              </div>
              <Button
                size="small"
                style={{ marginTop: 6 }}
                onClick={(e) => {
                  e.stopPropagation()
                  doStart()
                }}
              >
                重试
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
```

注意：需要安装 `@ant-design/icons`（项目中已有使用，无需额外安装）。如果项目中未使用过这些图标，改用文字替代即可。

- [x] **Step 2: 确认图标依赖**

```bash
cd frontend && grep -r "ant-design/icons" src/ | head -5
```

如果项目中已有使用 `@ant-design/icons` 则无需额外处理。如果没有，将图标替换为文字（如 "✓", "⚠", "⏳"）。

- [x] **Step 3: Commit**

```bash
git add frontend/src/pages/StockAnalysis/CollectCard.tsx
git commit -m "feat: add CollectCard component for kline data collection UI"
```

---

### Task 6: 集成 — SearchPanel 和 StockAnalysis 页面串联

**Files:**
- Modify: `frontend/src/pages/StockAnalysis/SearchPanel.tsx`
- Modify: `frontend/src/pages/StockAnalysis/index.tsx`

**Interfaces:**
- Consumes: `CollectCard` (from Task 5)
- Produces: 完整的用户流程：搜索 → 采集卡片 → 完成后生成报告

改动逻辑：
- `SearchPanel` 增加一个 `onCollect` 回调（替代直接 `onSelect`），让 StockAnalysis 页面控制流程
- `StockAnalysis` 页面增加"采集中"状态：选中股票后先显示 CollectCard，CollectCard 完成后才触发报告生成

- [x] **Step 1: 修改 `SearchPanel.tsx` — 将点击行为改为触发采集**

当前 `SearchPanel` 中 `onSelect` 直接传递给 `StockSearch` 和最近报告列表。需要修改为：点击后传递给父组件，由父组件决定先采集还是直接报告。

实际上 `SearchPanel` 本身不需要改动——它的 `onSelect` 回调已经把选中的 `StockBrief` 传给父组件。改动集中在父组件 `StockAnalysis/index.tsx`。

- [x] **Step 2: 修改 `StockAnalysis/index.tsx` — 增加采集阶段**

将现有的流程：
```
搜索 → 直接生成报告（SSE）
```
改为：
```
搜索 → 显示 CollectCard（采集中）→ 采集完成后点击 → 生成报告（SSE）
```

修改 `StockAnalysis/index.tsx`，在文件顶部添加导入：

```tsx
import CollectCard from './CollectCard'
```

修改 `StockAnalysis` 组件，增加 `collecting` 状态：

```tsx
export default function StockAnalysis() {
  const [collecting, setCollecting] = useState<StockBrief | null>(null)
  const [selected, setSelected] = useState<StockBrief | null>(null)
  const [progress, setProgress] = useState<ReportProgressEvent | null>(null)
  const [report, setReport] = useState<StockReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)

  const cancel = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
  }, [])

  // 搜索面板点击：进入采集阶段
  const handleSelect = useCallback((stock: StockBrief) => {
    cancel()
    setCollecting(stock)
    setSelected(null)
    setReport(null)
    setError(null)
    setProgress(null)
  }, [cancel])

  // 采集完成：进入报告生成阶段
  const handleCollectComplete = useCallback(
    (stock: StockBrief) => {
      setCollecting(null)
      setSelected(stock)
      setReport(null)
      setError(null)
      setProgress({ stage: 'fetching_data', progress: 5, message: '连接后端...' })
      cancelRef.current = streamReport(stock.code, {
        onProgress: (ev) => setProgress(ev),
        onReport: (r) => setReport(r),
        onError: (msg) => setError(msg),
        onComplete: () => {
          cancelRef.current = null
        }
      })
    },
    [cancel] // cancel 在内部未直接调用但 cancelRef 被 handleSelect 管理
  )

  useEffect(() => cancel, [cancel])

  const generating = selected !== null && report === null && error === null
  const hasReportError = report !== null && !!report.error
  const pct = progress?.progress ?? 0

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      {/* 搜索面板：无采集、无报告时显示 */}
      {collecting === null && selected === null && (
        <SearchPanel onSelect={handleSelect} />
      )}

      {/* 采集阶段：显示 CollectCard */}
      {collecting !== null && (
        <div style={{ maxWidth: 560, margin: '80px auto' }}>
          <div style={{ marginBottom: 10 }}>
            <a onClick={() => { setCollecting(null) }} style={{ fontSize: 12 }}>
              ← 重新搜索
            </a>
          </div>
          <h3 style={{ marginBottom: 8 }}>数据采集</h3>
          <CollectCard stock={collecting} onComplete={handleCollectComplete} />
        </div>
      )}

      {/* 以下为原有的报告生成/展示逻辑，保持不变 */}
      {generating && (
        <div
          style={{
            height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          <Card style={{ width: 420, textAlign: 'center' }}>
            <h3 style={{ marginBottom: 16 }}>
              正在生成 {selected?.name}（{selected?.code}）报告
            </h3>
            <div style={{ position: 'relative', margin: '12px 0 6px' }}>
              <div style={{ height: 10, background: 'var(--bg-elevated)', borderRadius: 5, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${pct}%`, height: '100%', borderRadius: 5,
                    background: 'var(--primary)', transition: 'width 0.4s'
                  }}
                />
              </div>
              <div style={{ marginTop: 10, fontSize: 13 }}>{progress?.message}</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 4 }}>
                {STAGE_LABELS[progress?.stage ?? ''] ?? ''} · {pct}%
              </div>
            </div>
          </Card>
        </div>
      )}

      {error && (
        <Alert
          type="error"
          showIcon
          message="报告生成失败"
          description={error}
          style={{ maxWidth: 560, margin: '80px auto' }}
        />
      )}

      {hasReportError && (
        <>
          <div style={{ marginBottom: 10 }}>
            <a onClick={() => { setSelected(null); setReport(null) }} style={{ fontSize: 12 }}>
              ← 重新搜索
            </a>
          </div>
          <Alert
            type="error"
            showIcon
            message="报告生成失败"
            description={report!.error}
            style={{ maxWidth: 560, margin: '40px auto' }}
          />
        </>
      )}

      {report && !hasReportError && (
        <>
          <div style={{ marginBottom: 10 }}>
            <a
              onClick={() => {
                setSelected(null)
                setReport(null)
              }}
              style={{ fontSize: 12 }}
            >
              ← 重新搜索
            </a>
          </div>
          <ReportView report={report} />
        </>
      )}
    </div>
  )
}
```

**注意事项：**
- 原有 `start` 函数逻辑拆分为 `handleSelect`（进入采集）和 `handleCollectComplete`（采集完成后生报告）
- `SearchPanel` 的 `onSelect` prop 改为指向 `handleSelect`
- 需要确保 `import { Alert, Card } from 'antd'` 和 `import { streamReport } from '@/services/api'` 等原有导入保持不变
- 新增 `import CollectCard from './CollectCard'`

- [x] **Step 3: 构建前端验证编译通过**

```bash
cd frontend && npm run build
```

- [x] **Step 4: 手动测试完整流程**

1. 启动后端: `cd backend && python main.py`
2. 启动前端: `cd frontend && npm run dev`
3. 打开浏览器访问前端
4. 搜索股票（如 "000001"）并点击
5. 确认出现采集卡片，进度条推进
6. 等待采集完成，点击卡片
7. 确认报告正常生成

- [x] **Step 5: Commit**

```bash
git add frontend/src/pages/StockAnalysis/index.tsx frontend/src/pages/StockAnalysis/CollectCard.tsx
git commit -m "feat: integrate collect flow into stock analysis page"
```

---

## 注意事项与边界情况

### ProMax pro_bar 5min 支持

`ProMaxSource.pro_bar` 已实现，但 5 分钟频率是否被上游实际支持取决于 ProMax 网关的能力配置。如果 `freq="5min"` 返回错误，可能的原因：

1. **上游不支持该频率** → 错误会被 `_parse_error` 捕获，CollectCard 显示错误状态
2. **权限不足** → 同上
3. **数据窗口限制** → 减小分窗粒度（改为按周或按日）

建议在实现后先用单个请求手动验证：
```bash
curl "https://pcd.mobcvb.cn/tushare/pro/pro_bar?ts_code=000001.SZ&freq=5min&start_date=20260901&end_date=20260919" \
  -H "X-API-Key: YOUR_KEY"
```

### 数据库容量

- 单股 3 年 ≈ 36,000 行，100 只股票 ≈ 360 万行
- MySQL 无压力；SQLite 建议添加 WAL 模式（已默认）
- 如后续需要，可添加按股票/日期清理旧数据的接口

### 可扩展点（本期不实现）

- 批量采集多只股票（队列）
- 采集完成后利用 5 分钟线做高频技术分析
- 数据更新（只拉最新增量）
- 采集历史持久化到数据库（当前为内存，重启丢失进度）
