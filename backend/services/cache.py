"""JSON 文件缓存 v2（design.md §4.1.7 缓存、分页与质量元信息）。

- 缓存键: provider/schema_version/方法/规范参数/fields 顺序/adjust/anchor
- 目录隔离: <CACHE_DIR>/<provider>/<subdir>/<name>.json
  （旧阶段2 无来源标记的缓存位于 provider 目录之外，真实模式不会读到）
- 文件内含 `_cached_at` + `_data_meta`（source/api/as_of/fetched_at/trade_date/
  is_stale/adjust/anchor/coverage/missing_fields/warnings）
- DataFrame 通过 attrs["data_meta"] 挂载元信息；dict 用保留键 `_data_meta`
- 失败不覆盖好缓存；成功空结果短缓存；可恢复故障允许有限龄 stale 回退
- 同 key 并发请求合并（进程内）
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from config import settings
from services.providers.errors import DataSourceError

logger = logging.getLogger("stockpanel.cache")

_CACHED_AT = "_cached_at"
_SCHEMA = "_schema"
_KIND = "_kind"
_META = "_data_meta"

# 进程内 inflight 合并: key -> 锁
_inflight: dict[str, threading.Lock] = {}
_inflight_guard = threading.Lock()


class CacheEntry:
    """一次缓存读写的封装。"""

    def __init__(self, provider: str, subdir: str = "", name: str | None = None):
        self.provider = provider
        self.subdir = subdir
        self.name = name

    # -- 路径 ---------------------------------------------------------------

    def _dir(self) -> Path:
        d = settings.CACHE_DIR / self.provider
        if self.subdir:
            d = d / self.subdir
        return d

    def path(self, key: str) -> Path:
        self._dir().mkdir(parents=True, exist_ok=True)
        return self._dir() / f"{self.name or key}.json"

    # -- 读写 ---------------------------------------------------------------

    def read(self, key: str, ttl: float) -> tuple[dict | None, bool]:
        """返回 (payload, is_expired_hit)。payload 为 None 表示无可用缓存。"""
        path = self.path(key)
        if not path.is_file():
            return None, False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("缓存损坏，忽略: %s", path.name)
            return None, False
        if payload.get(_SCHEMA) != settings.STOCK_CACHE_SCHEMA_VERSION:
            logger.info("缓存 schema 版本不符，忽略: %s", path.name)
            return None, False
        cached_at = float(payload.get(_CACHED_AT, 0) or 0)
        age = time.time() - min(path.stat().st_mtime, cached_at)
        if age < ttl:
            return payload, False
        if age <= settings.STOCK_STALE_MAX_AGE:
            return payload, True  # 过期但在 stale 回退窗口内
        return None, False

    def write(self, key: str, kind: str, data, meta: dict) -> None:
        payload = {
            _SCHEMA: settings.STOCK_CACHE_SCHEMA_VERSION,
            _CACHED_AT: time.time(),
            _KIND: kind,
            _META: meta,
            "data": data if kind == "json" else None,
            "columns": list(data.columns) if kind == "dataframe" else None,
            "records": data.to_dict(orient="records") if kind == "dataframe" else None,
        }
        path = self.path(key)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=_json_default),
                           encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.exception("缓存写入失败: %s", path.name)
            tmp.unlink(missing_ok=True)

    def load(self, payload: dict):
        """payload -> (result, meta)。DataFrame 重新挂 attrs["data_meta"]。"""
        kind = payload.get(_KIND)
        meta = dict(payload.get(_META) or {})
        if kind == "dataframe":
            df = pd.DataFrame(payload["records"], columns=payload["columns"])
            df.attrs["data_meta"] = meta
            return df, meta
        data = payload["data"]
        if isinstance(data, dict):
            data = {**data, "_data_meta": meta}
        return data, meta

    def age_seconds(self, key: str) -> float | None:
        path = self.path(key)
        if not path.is_file():
            return None
        return time.time() - min(path.stat().st_mtime,
                                 float(_read_cached_at(path) or 0))


def _is_empty_result(result) -> bool:
    """成功空结果判定: 空 DataFrame / 全 None 的 dict / 空列表。"""
    if isinstance(result, pd.DataFrame):
        return result.empty
    if isinstance(result, dict):
        vals = [v for k, v in result.items() if not k.startswith("_")]
        return not vals or all(v is None for v in vals)
    if isinstance(result, list):
        return not result
    return False


def _empty_expired(payload: dict) -> bool:
    """空结果缓存超过 CACHE_TTL_EMPTY → 视为过期重新拉取。"""
    meta = payload.get(_META) or {}
    if not meta.get("_empty"):
        return False
    cached_at = float(payload.get(_CACHED_AT, 0) or 0)
    return time.time() - cached_at > settings.CACHE_TTL_EMPTY


def _read_cached_at(path: Path) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return float(payload.get(_CACHED_AT, 0) or 0)
    except (OSError, ValueError, TypeError):
        return None


def _json_default(obj):
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(obj)


def cache_key(provider: str, method: str, params: dict, *, extra: str | None = None) -> str:
    """缓存键: provider/schema/方法/参数（含 fields 顺序/adjust/anchor）。"""
    material = json.dumps(
        {"p": provider, "m": method, "v": settings.STOCK_CACHE_SCHEMA_VERSION,
         "args": params, "x": extra or ""},
        sort_keys=True, ensure_ascii=False)
    return hashlib.md5(material.encode("utf-8")).hexdigest()[:20]


def run_cached(
    provider: str,
    subdir: str,
    name: str | None,
    key: str,
    ttl: float,
    producer: Callable[[], tuple],
    *,
    stale_on_retryable: bool = True,
) -> tuple[object, dict, bool]:
    """带缓存的调用模板。

    producer() -> (result, meta)；result 为 DataFrame 或 dict/list。
    返回 (result, meta, from_stale)。

    - 命中且未过期 → 直接返回（meta.fetched_at 保留原始值）
    - 失败（可恢复错误）且存在 stale 窗口内缓存 → 回退并标注 is_stale
    - 成功空结果由调用方传 ttl=CACHE_TTL_EMPTY 控制
    """
    entry = CacheEntry(provider, subdir, name)
    path_key = name or key

    payload, expired = entry.read(path_key, ttl)
    if payload is not None and not expired and not _empty_expired(payload):
        return (*entry.load(payload), False)

    # 同 key 并发合并
    lock_key = f"{provider}/{subdir}/{path_key}"
    with _inflight_guard:
        lock = _inflight.setdefault(lock_key, threading.Lock())
    if lock.acquire(blocking=False):
        try:
            payload, expired = entry.read(path_key, ttl)  # 等锁期间可能已被他人写入
            if payload is not None and not expired and not _empty_expired(payload):
                return (*entry.load(payload), False)
            result, meta = producer()
            meta = dict(meta or {})
            if _is_empty_result(result):
                meta = {**meta, "_empty": True}  # 成功空结果只短缓存（60s）
            kind = "dataframe" if isinstance(result, pd.DataFrame) else "json"
            entry.write(path_key, kind, result, meta)
            return result, meta, False
        except DataSourceError as exc:
            # 可恢复故障: stale 窗口内的旧缓存回退（保留原 fetched_at，标注过期原因）
            payload, _ = entry.read(path_key, math.inf)
            if stale_on_retryable and getattr(exc, "retryable", False) and payload is not None:
                result, meta = entry.load(payload)
                meta = {**meta, "is_stale": True,
                        "stale_reason": f"来源暂不可用，回退旧缓存: {exc.message}"}
                if isinstance(result, pd.DataFrame):
                    result.attrs["data_meta"] = meta
                elif isinstance(result, dict):
                    result = {**result, "_data_meta": meta}
                logger.warning("回退旧缓存(%s): %s", provider, meta["stale_reason"])
                return result, meta, True
            raise
        finally:
            # 先注销再释放：release 后等待方才开始执行，此时 inflight 已无此锁，
            # 新请求会重建锁并合并，而不是拿到已弹出的旧锁引用造成双跑。
            with _inflight_guard:
                if _inflight.get(lock_key) is lock:
                    _inflight.pop(lock_key, None)
            lock.release()
    else:
        # 已有请求在算: 等它完成后读缓存
        with lock:
            payload, expired = entry.read(path_key, ttl)
        if payload is not None and not expired:
            return (*entry.load(payload), False)
        # 等待方拿不到缓存（原请求失败），自行调用生产者
        result, meta = producer()
        return result, meta, False


# stale 回退直接判断 errors.DataSourceError.retryable（不再需要内部信号类）


# -- 统计与清除（阶段2 API 保持兼容） ----------------------------------------

def get_cache_stats() -> dict:
    """缓存统计: JSON 文件数量与总大小（含 provider 子目录）。"""
    total_size = 0
    file_count = 0
    for f in settings.CACHE_DIR.rglob("*.json"):
        if f.is_file():
            file_count += 1
            total_size += f.stat().st_size
    return {
        "file_count": file_count,
        "total_size": total_size,
        "total_size_human": _human_size(total_size),
        "cache_dir": str(settings.CACHE_DIR),
    }


def clear_cache() -> int:
    """清空全部缓存文件（含 provider 子目录与旧版文件），返回删除数。"""
    removed = 0
    if settings.CACHE_DIR.exists():
        for f in settings.CACHE_DIR.rglob("*.json"):
            if f.is_file():
                f.unlink()
                removed += 1
    logger.info("缓存已清空, removed=%s", removed)
    return removed


def _human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


# -- 兼容阶段2 的装饰器（mock 路径/外部复用；键含调用参数 hash） --------------

def file_cache(ttl_seconds: float, cache_dir: str | Path = "", name: str | None = None,
               provider: str = "mock"):
    """兼容旧版装饰器: 缓存于 <CACHE_DIR>/<provider>/<cache_dir>/。"""

    def decorator(func: Callable):
        sub = Path(cache_dir)
        root = settings.CACHE_DIR / provider / sub

        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            root.mkdir(parents=True, exist_ok=True)
            digest = hashlib.md5(json.dumps(
                {k: repr(v) for k, v in sorted(kwargs.items())},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            path = root / f"{name or func.__name__}_{digest}.json"
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    age = time.time() - min(path.stat().st_mtime,
                                            float(payload.get(_CACHED_AT, 0) or 0))
                    if age < ttl_seconds:
                        if payload.get(_KIND) == "dataframe":
                            df = pd.DataFrame(payload["records"], columns=payload["columns"])
                            return df
                        return payload["data"]
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    pass
            result = func(*args, **kwargs)
            kind = "dataframe" if isinstance(result, pd.DataFrame) else "json"
            payload = {_SCHEMA: settings.STOCK_CACHE_SCHEMA_VERSION, _CACHED_AT: time.time(),
                       _KIND: kind, "data": None if kind == "dataframe" else result,
                       "columns": list(result.columns) if kind == "dataframe" else None,
                       "records": result.to_dict(orient="records") if kind == "dataframe" else None}
            tmp = path.with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False, default=_json_default),
                               encoding="utf-8")
                tmp.replace(path)
            except OSError:
                tmp.unlink(missing_ok=True)
            return result

        return wrapper

    return decorator
