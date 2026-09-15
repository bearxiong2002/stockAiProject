"""get_stock_news 冷缓存空结果重试测试（不联网）。

ProMax 网关首次请求（X-Cache=MISS）会返回 code=0 的空结果，稍后同参数重试才命中缓存。
run: .venv/bin/python tests/test_news_retry.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.data_fetcher as data_fetcher
from services.data_fetcher import DataFetcher
from services.providers.baseclient import FetchResult

PASS = FAIL = 0
FIELDS = ["datetime", "title", "content", "channels"]


def check(name: str, cond, detail="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


class FakePM:
    """按顺序返回预设 rows 的 ProMax 桩，记录 news 调用参数。"""

    def __init__(self, *responses: list[list]):
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def news(self, src, start_date, end_date, limit=200):
        self.calls.append((src, start_date, end_date, limit))
        rows = self.responses.pop(0) if self.responses else []
        return FetchResult(provider="promax", api="news", fields=FIELDS, rows=rows,
                           fetched_at=time.time())

    def major_news(self, *args, **kwargs):
        raise AssertionError("major_news 不应被调用")


def make_fetcher(pm: FakePM) -> DataFetcher:
    f = DataFetcher(mode="hybrid")  # hybrid 先走 news（promax 模式只走 major_news）
    f._real["promax"] = pm
    f._mem["as_of"] = (time.time(), "20260911")  # 避免 _as_of 查交易日历
    f._stock_name_of = lambda ts: "宁德时代"
    return f


HIT = [["2026-09-11 19:05:54", "宁德时代：今日首次回购公司A股股份60.43万股",
        "【宁德时代：今日首次回购】财联社9月11日电……", "cls"]]
OTHER = [["2026-09-11 10:00:00", "央行开展逆回购操作", "【央行开展逆回购操作】……", "cls"]]


def warnings_of(df) -> list[str]:
    return df.attrs.get("data_meta", {}).get("warnings") or []


def test_retry_on_cold_empty():
    print("首次空结果 → 同参数重试一次 → 拿到数据")
    pm = FakePM([], HIT)
    df = make_fetcher(pm).get_stock_news("300750")
    check("news 调用 2 次", len(pm.calls) == 2, f"got {len(pm.calls)}")
    check("两次请求参数完全相同（命中网关缓存键）",
          len(pm.calls) == 2 and pm.calls[0] == pm.calls[1], str(pm.calls))
    check("返回关联新闻 1 条", len(df) == 1, f"got {len(df)}")
    check("无数据 warning 不出现", not warnings_of(df), str(warnings_of(df)))


def test_no_retry_when_first_has_rows():
    print("首次即有数据 → 不重试")
    pm = FakePM(HIT)
    df = make_fetcher(pm).get_stock_news("300750")
    check("news 调用 1 次", len(pm.calls) == 1, f"got {len(pm.calls)}")
    check("返回关联新闻 1 条", len(df) == 1, f"got {len(df)}")
    # 3 天窗口约 500 条，limit=200 会被上游截断成最早的 200 条
    check("请求 limit=2000", pm.calls and pm.calls[0][3] == 2000, str(pm.calls))


def test_no_retry_when_rows_but_unrelated():
    print("上游有数据但未提及该股 → 不重试，warning 说明未关联")
    pm = FakePM(OTHER)
    df = make_fetcher(pm).get_stock_news("300750")
    check("news 调用 1 次", len(pm.calls) == 1, f"got {len(pm.calls)}")
    check("返回空表", df.empty)
    check("warning 说明未提及该股", any("未提及" in w for w in warnings_of(df)),
          str(warnings_of(df)))


def test_still_empty_after_retry():
    print("重试后仍为空 → 只重试一次，warning 说明已重试")
    pm = FakePM([], [])
    df = make_fetcher(pm).get_stock_news("300750")
    check("news 调用 2 次（不无限重试）", len(pm.calls) == 2, f"got {len(pm.calls)}")
    check("返回空表", df.empty)
    check("warning 说明已重试", any("重试" in w for w in warnings_of(df)),
          str(warnings_of(df)))


def main() -> int:
    data_fetcher.NEWS_EMPTY_RETRY_DELAY = 0  # 测试不等待
    test_retry_on_cold_empty()
    test_no_retry_when_first_has_rows()
    test_no_retry_when_rows_but_unrelated()
    test_still_empty_after_retry()
    print(f"\n通过 {PASS}，失败 {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
