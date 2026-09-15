"""阶段 7 自测脚本（锁定 mock 模式，离线运行，不联网）。

运行方式:
    cd backend && .venv/bin/python tests/selftest_phase7.py

覆盖 implementation-plan.md 阶段 7 审核检查点:
    1 自选股 CRUD（去重/持久化/排序） / 2 自选股行情数据 / 3 排序（前端列排序
    由前端 Table 实现，后端提供数据） / 4 指数卡片 / 5 热力图数据 / 6 资金流向
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="stockpanel_p7_")
os.environ["STOCK_DATA_MODE"] = "mock"
os.environ["STOCKPANEL_DATA_DIR"] = _TMP

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from models.database import init_db
from models.schemas import WatchlistCreate, WatchlistSortPayload

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def test_watchlist_crud():
    print("\n[1] 自选股 CRUD + 行情数据")
    from api import watchlist as api

    async def flow():
        # 单 event loop 执行全部 DB 操作（aiosqlite 连接不可跨 loop）
        checks = {}
        empty = await api.list_watchlist()
        checks["初始为空"] = len(empty["items"]) == 0
        a = await api.add_watchlist(WatchlistCreate(code="600519"))
        checks["添加返回名称"] = a["stock_name"] == "贵州茅台"
        checks["行情字段齐全"] = (a["latest_price"] is not None
                              and a["pct_change"] is not None
                              and a["industry"] is not None)
        b = await api.add_watchlist(WatchlistCreate(code="000001"))
        checks["第二次添加"] = b["stock_name"] == "平安银行"
        dup_ok = False
        try:
            await api.add_watchlist(WatchlistCreate(code="600519"))
        except Exception as exc:
            detail = str(getattr(exc, "detail", exc))
            dup_ok = "已在自选列表" in detail
        checks["重复添加 409"] = dup_ok
        listed = await api.list_watchlist()
        checks["列表 2 条"] = len(listed["items"]) == 2
        await api.sort_watchlist(WatchlistSortPayload(codes=["000001", "600519"]))
        listed2 = await api.list_watchlist()
        checks["排序生效"] = listed2["items"][0]["code"] == "000001"
        removed = await api.remove_watchlist("600519")
        checks["移除成功"] = removed["ok"] is True
        listed3 = await api.list_watchlist()
        checks["移除后 1 条"] = len(listed3["items"]) == 1
        checks["data_meta 透传"] = isinstance(listed3["data_meta"], dict)
        return checks, listed3

    checks, listed3 = asyncio.run(flow())
    for name, ok in checks.items():
        check(name, ok)
    return listed3


def test_market():
    print("\n[2] 大盘数据端点")
    from api import market as api

    idx = api.indices()
    check("4 个指数", len(idx["items"]) == 4, str(len(idx["items"])))
    names = [i["name"] for i in idx["items"]]
    check("指数名单", set(names) >= {"上证指数", "深证成指", "创业板指", "科创50"}, str(names))
    for it in idx["items"]:
        if it.get("index_kline") is None and it.get("error"):
            check(f"{it['name']} 无数据注记", True)
            continue
        check(f"{it['name']} 数据完整", it.get("close") is not None
              and it.get("pct_change") is not None, str(it)[:100])
        check(f"{it['name']} 迷你 30 点", len(it.get("sparkline") or []) == 30,
              str(len(it.get("sparkline") or [])))
    sec = api.sectors()
    check("行业板块 ≥10", len(sec_items := sec["items"]) >= 10, str(len(sec_items)))
    check("板块含涨跌幅", all(s.get("pct_change") is not None for s in sec_items[:5]))
    ff = api.fund_flow(10)
    check("资金流 10 日", len(ff["items"]) == 10, str(len(ff["items"])))
    check("资金流含主力净额", ff["items"][0]["main_net_inflow"] is not None)
    stat = api.statistics()
    check("涨跌统计字段", {"up", "down", "flat"} <= set(stat.keys()), str(stat)[:120])
    check("家数非负", all((stat.get(k) or 0) >= 0 for k in ("up", "down", "flat")))
    print("  statistics:", {k: stat.get(k) for k in ("as_of", "up", "down", "flat",
                                                    "limit_up", "limit_down")})
    return idx


def test_market_boundaries():
    print("\n[3] 边界")
    from api import market as api
    try:
        api.fund_flow(100)
        check("days>30 拒绝", False, "未抛出")
    except Exception as exc:
        check("资金流 days 校验", "1~30" in str(getattr(getattr(exc, "detail", None), "detail", exc)))
    from api import watchlist as wl
    try:
        asyncio.run(wl.add_watchlist(WatchlistCreate(code="")))  # 无 DB 访问（参数校验在前）
        check("空 code 拒绝", False, "未抛出")
    except Exception as exc:
        check("空 code 拒绝", "缺少 code" in str(getattr(getattr(exc, "detail", None), "detail", str(exc))))


def main() -> int:
    asyncio.run(init_db())
    test_watchlist_crud()
    test_market()
    test_market_boundaries()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败  (临时数据目录: {_TMP})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
