"""阶段 8 自测脚本（锁定 mock 数据源 + httpx.MockTransport，离线运行，不联网）。

运行方式:
    cd backend && .venv/bin/python tests/selftest_phase8.py

覆盖 implementation-plan.md 阶段 8 审核检查点（离线可验证部分）:
    1 AI 新闻分析（协议/解析/降级） / 2 AI 综合报告（字段契约）
    3 AI 降级（无 Key / 调用失败 / 无新闻） / 4 AI 持仓建议（端点契约）
    5 LLM 测试（成功/失败分类） / 6 配置 API（加密存储 + 脱敏）
    7 生产模式（SPA 静态托管 + api 不回退）
"""
from __future__ import annotations

import json
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="stockpanel_p8_")
os.environ["STOCK_DATA_MODE"] = "mock"
os.environ["STOCKPANEL_DATA_DIR"] = _TMP
os.environ.pop("LLM_PROVIDER", None)
os.environ.pop("LLM_API_KEY", None)

import asyncio
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from models.database import init_db  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


# ---------------------------------------------------------------------------
# 1. Prompt 模板与渲染
# ---------------------------------------------------------------------------

def test_prompts():
    print("\n[1] Prompt 模板")
    from services.ai_analyzer import PROMPTS_DIR, load_prompt, render_prompt
    for name in ("news_sentiment", "stock_report", "portfolio_advice"):
        path = PROMPTS_DIR / f"{name}.txt"
        check(f"{name}.txt 存在", path.is_file(), str(path))
        text = load_prompt(name)
        check(f"{name} 含占位符", "{" in text and "}" in text)
    rendered = render_prompt(load_prompt("news_sentiment"),
                             {"stock_name": "贵州茅台", "code": "600519",
                              "today": "2026-09-13", "news_text": "1. 测试新闻"})
    check("占位符替换", "贵州茅台" in rendered and "{news_text}" not in rendered)
    check("JSON 花括号未被破坏", '"overall_sentiment"' in rendered)


# ---------------------------------------------------------------------------
# 2. 密钥加密与配置解析
# ---------------------------------------------------------------------------

def test_secret_box():
    print("\n[2] 密钥加密存储")
    from config import settings
    from services.llm_config import SecretBox
    box = SecretBox()
    token = box.encrypt("sk-test-1234567890")
    check("密文不含明文", "sk-test-1234567890" not in token, token[:24])
    check("密文带算法前缀", token.startswith(("enc1:", "b64:")), token[:8])
    check("解密还原", box.decrypt(token) == "sk-test-1234567890")
    check("密钥文件生成", (settings.APP_DATA_DIR / "secret.key").is_file())
    mode = (settings.APP_DATA_DIR / "secret.key").stat().st_mode & 0o777
    check("密钥文件权限 600", mode == 0o600, oct(mode))
    check("空值往返", box.encrypt("") == "" and box.decrypt("") == "")
    check("坏密文返回 None", box.decrypt("enc1:not-a-token") is None)
    box2 = SecretBox()  # 同一密钥文件可解密（持久化）
    check("跨实例解密", box2.decrypt(token) == "sk-test-1234567890")


def test_config_resolution():
    print("\n[3] LLM 配置解析与脱敏")
    from services.llm_config import (get_llm_config, mask_key, provider_defaults,
                                     resolve_llm_config)
    cfg = resolve_llm_config({"provider": "claude", "api_key": "sk-abcdefghijkl",
                              "api_base": "", "model": "", "sources": {}})
    check("provider 默认 base", cfg["api_base"] == "https://api.anthropic.com", cfg["api_base"])
    check("provider 默认 model", bool(cfg["model"]), cfg["model"])
    check("available=True", cfg["available"] is True)
    no_key = resolve_llm_config({"provider": "claude", "api_key": "", "api_base": "",
                                 "model": "", "sources": {}})
    check("无 Key 不可用", no_key["available"] is False and "API Key" in no_key["disabled_reason"])
    off = resolve_llm_config({"provider": "none", "api_key": "sk-x", "api_base": "",
                              "model": "", "sources": {}})
    check("provider=none 关闭", off["available"] is False)
    bad = resolve_llm_config({"provider": "bogus", "api_key": "sk-x", "api_base": "",
                              "model": "", "sources": {}})
    check("未知 provider 按关闭处理", bad["provider"] == "none")
    check("密钥掩码", mask_key("sk-abcdefghijkl") == "sk-****ijkl", mask_key("sk-abcdefghijkl"))
    check("短密钥掩码", mask_key("short") == "****")
    env_default = get_llm_config()
    check("默认未配置", env_default["available"] is False)
    defaults = provider_defaults()
    check("设置页默认值结构", {"default_bases", "default_models", "model_suggestions",
                        "providers"} <= set(defaults.keys()))


# ---------------------------------------------------------------------------
# 4. AIAnalyzer 协议（MockTransport）
# ---------------------------------------------------------------------------

SENTIMENT_JSON = {
    "overall_sentiment": "positive",
    "sentiment_score": 42.5,
    "key_events": [
        {"event": "半年报营收增长", "impact": "基本面改善", "sentiment": "positive"},
        {"event": "股东减持计划", "impact": "短期承压", "sentiment": "negative"},
        {"event": "机构调研", "impact": "关注度提升", "sentiment": "利好"},
    ],
    "summary": "近期新闻整体偏正面，业绩与机构关注度提升，但存在股东减持扰动。",
}
REPORT_JSON = {
    "summary": "综合来看，公司基本面稳健，技术面中性偏弱，整体维持谨慎推荐。",
    "technical_comment": "均线纠缠，MACD 零轴附近，量能一般。",
    "fundamental_comment": "估值处于行业中枢，盈利保持增长。",
    "risks": ["技术面趋势偏弱", "股东减持扰动", "行业景气度回落风险"],
    "catalysts": ["机构调研密集", "新产品放量"],
    "recommendation": "可少量参与，跌破关键均线则观望。",
}
ADVICE_JSON = {
    "overall_assessment": "组合集中度中等，Beta 偏低，整体风险可控，但相关性偏高。",
    "risk_warnings": ["两只持仓相关性偏高", "行业暴露集中在金融"],
    "suggestions": ["适度分散行业配置", "设置止损纪律", "关注流动性变化"],
    "rebalance_ideas": ["降低高相关个股权重"],
}

_calls: list[dict] = []


def _claude_handler(content: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        _calls.append({"url": str(request.url), "headers": dict(request.headers),
                       "body": json.loads(request.content.decode())})
        text = "```json\n" + json.dumps(content, ensure_ascii=False) + "\n```"
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "分析如下：\n" + text}],
            "usage": {"input_tokens": 10, "output_tokens": 10}})
    return handler


def _openai_handler(content: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        _calls.append({"url": str(request.url), "headers": dict(request.headers),
                       "body": json.loads(request.content.decode())})
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(content, ensure_ascii=False)}}]})
    return handler


def _claude_analyzer(content: dict):
    from services.ai_analyzer import AIAnalyzer
    from services.llm_config import resolve_llm_config
    cfg = resolve_llm_config({"provider": "claude", "api_key": "sk-test-key-123456",
                              "api_base": "https://api.anthropic.com",
                              "model": "claude-sonnet-5", "sources": {}})
    return AIAnalyzer(cfg, transport=httpx.MockTransport(_claude_handler(content)))


def test_analyzer_protocol():
    print("\n[4] AIAnalyzer 协议与解析（MockTransport）")
    _calls.clear()
    analyzer = _claude_analyzer(SENTIMENT_JSON)
    news = [{"title": "贵州茅台发布半年报", "content": "营收增长",
             "pub_time": "2026-09-12 09:00", "source": "证券时报"}]
    result = analyzer.analyze_news_sentiment(news, stock_name="贵州茅台", code="600519")
    check("claude 情绪结果解析", result is not None and result["sentiment_score"] == 42.5,
          str(result))
    check("中文情绪标签归一化", result["key_events"][2]["sentiment"] == "positive",
          str(result["key_events"][2]))
    check("情绪分布统计", result["distribution"] == {"positive": 2, "negative": 1,
                                             "neutral": 0}, str(result["distribution"]))
    call = _calls[-1]
    check("claude URL /v1/messages", call["url"].endswith("/v1/messages"), call["url"])
    check("claude 鉴权头", call["headers"].get("x-api-key") == "sk-test-key-123456")
    check("anthropic-version 头", call["headers"].get("anthropic-version") == "2023-06-01")
    check("prompt 注入新闻标题", "贵州茅台发布半年报" in call["body"]["messages"][0]["content"])

    analyzer = _claude_analyzer(REPORT_JSON)
    report = analyzer.generate_analysis_report({
        "stock_info": {"code": "600519", "name": "贵州茅台", "latest_price": 1500.0,
                       "pct_change": 1.2, "trade_date": "2026-09-11"},
        "rating": {"score": 12.3, "label": "谨慎推荐", "weights": {"technical": 0.5}},
        "technical_result": {"score": 20.0, "rating": "中性",
                             "components": {"trend": {"score": 30, "signals": []}},
                             "signals": [{"signal": "MACD 金叉"}]},
        "fundamental_result": {"score": 40.0, "rating": "看多", "incomplete": False,
                               "valuation": {"score": 50, "items": [
                                   {"name": "PE", "value": 28.5, "industry_median": 30}]}},
        "fund_flow": {"main_net_inflow_5d": -1.2, "trend": "outflow"},
        "news_sentiment": {"overall": "positive", "score": 42.5, "summary": "偏正面",
                           "key_events": []},
        "kline_summary": {"close": 1500.0, "ma_5": 1490.0, "ma_20": 1480.0,
                          "ma_60": 1450.0, "pct_20d": 3.2, "pct_60d": 8.1},
    })
    check("综合报告字段完整", report is not None and {"summary", "technical_comment",
          "fundamental_comment", "risks", "catalysts", "recommendation"} <= set(report.keys()),
          str(report))
    check("风险/催化为列表", isinstance(report["risks"], list)
          and isinstance(report["catalysts"], list) and len(report["risks"]) == 3)
    check("上下文含技术信号", "MACD 金叉" in _calls[-1]["body"]["messages"][0]["content"])

    _calls.clear()
    from services.ai_analyzer import AIAnalyzer
    from services.llm_config import resolve_llm_config
    cfg = resolve_llm_config({"provider": "openai", "api_key": "sk-oai-1234567890",
                              "api_base": "", "model": "", "sources": {}})
    oai = AIAnalyzer(cfg, transport=httpx.MockTransport(_openai_handler(ADVICE_JSON)))
    advice = oai.generate_portfolio_advice({
        "holdings": [{"stock_code": "600519", "stock_name": "贵州茅台", "quantity": 100,
                      "cost_price": 1400, "latest_price": 1500, "profit_pct": 7.1,
                      "weight": 60.0, "industry": "白酒"}],
        "risk_metrics": {"total_market_value": 150000, "sample_days": 120,
                         "var": {"95": {"pct": -1.75}}, "max_drawdown": {"max": -12.5},
                         "volatility": {"portfolio": 22.1, "index": 18.0},
                         "beta": 0.85, "sharpe": 0.9,
                         "concentration": {"hhi": 0.5, "top3_pct": 100, "level": "高",
                                           "count": 1},
                         "correlation": {"high_pairs": []}, "risk_level": "中等"},
        "sector_exposure": {"sectors": [{"industry": "白酒", "weight_pct": 100.0}]},
    })
    check("OpenAI 兼容协议建议解析", advice is not None and len(advice["suggestions"]) == 3,
          str(advice))
    check("openai URL /chat/completions", _calls[-1]["url"].endswith("/chat/completions"),
          _calls[-1]["url"])
    check("openai Bearer 鉴权",
          _calls[-1]["headers"].get("authorization") == "Bearer sk-oai-1234567890")
    check("系统消息存在", _calls[-1]["body"]["messages"][0]["role"] == "system")
    check("默认 base 生效", "api.openai.com" in _calls[-1]["url"], _calls[-1]["url"])


def test_analyzer_degradation():
    print("\n[5] AIAnalyzer 失败降级")
    from services.ai_analyzer import AIAnalyzer
    from services.llm_config import resolve_llm_config

    def unauthorized(request):
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    cfg = resolve_llm_config({"provider": "claude", "api_key": "sk-bad", "api_base": "",
                              "model": "", "sources": {}})
    analyzer = AIAnalyzer(cfg, transport=httpx.MockTransport(unauthorized))
    result = analyzer.analyze_news_sentiment([{"title": "t", "content": "c"}])
    check("401 返回 None", result is None)
    check("错误分类 auth", analyzer.last_error["category"] == "auth",
          str(analyzer.last_error))

    def bad_json(request):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "抱歉，我无法分析"}]})

    analyzer = AIAnalyzer(cfg, transport=httpx.MockTransport(bad_json))
    check("非 JSON 返回 None", analyzer.generate_analysis_report({"stock_info": {}}) is None)
    check("错误分类 bad_json", analyzer.last_error["category"] == "bad_json")

    def fail_network(request):
        raise httpx.ConnectError("boom", request=request)

    analyzer = AIAnalyzer(cfg, transport=httpx.MockTransport(fail_network))
    check("网络错误返回 None", analyzer.generate_portfolio_advice(
        {"holdings": [{"stock_code": "600519"}]}) is None)
    check("错误分类 network", analyzer.last_error["category"] == "network",
          str(analyzer.last_error))

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    analyzer = AIAnalyzer(cfg, transport=httpx.MockTransport(timeout))
    check("超时返回 None", analyzer.analyze_news_sentiment([{"title": "t"}]) is None)
    check("错误分类 timeout", analyzer.last_error["category"] == "timeout")

    def rate_limited(request):
        return httpx.Response(429, json={"error": {"message": "rate limit"}})

    analyzer = AIAnalyzer(cfg, transport=httpx.MockTransport(rate_limited))
    out = analyzer.test_connection()
    check("test_connection 限流分类", out["ok"] is False and out["category"] == "rate_limit",
          str(out))

    unconfigured = AIAnalyzer(resolve_llm_config(
        {"provider": "none", "api_key": "", "api_base": "", "model": "", "sources": {}}))
    check("未配置时方法返回 None",
          unconfigured.analyze_news_sentiment([{"title": "t"}]) is None
          and unconfigured.generate_analysis_report({}) is None
          and unconfigured.generate_portfolio_advice({}) is None)
    check("未配置 test_connection 分类",
          unconfigured.test_connection()["category"] == "not_configured")

    _calls.clear()
    ok_analyzer = _claude_analyzer(SENTIMENT_JSON)
    ping = ok_analyzer.test_connection()
    check("test_connection 成功", ping["ok"] is True and ping["latency_ms"] >= 0, str(ping))
    check("测试请求极小 max_tokens", _calls[-1]["body"]["max_tokens"] == 16,
          str(_calls[-1]["body"].get("max_tokens")))

    from services.ai_analyzer import AIAnalyzer
    from services.llm_config import resolve_llm_config as _resolve
    _calls.clear()
    oai_analyzer = AIAnalyzer(
        _resolve({"provider": "openai", "api_key": "sk-base-12345678", "api_base": "",
                  "model": "", "sources": {}}),
        transport=httpx.MockTransport(_openai_handler(SENTIMENT_JSON)))
    override = oai_analyzer.test_connection({"provider": "openai",
                                             "api_key": "sk-override-123456"})
    check("测试支持覆盖 provider", override["ok"] is True
          and override["provider"] == "openai", str(override))
    check("覆盖值生效", _calls[-1]["headers"].get("authorization")
          == "Bearer sk-override-123456")


def test_json_extraction():
    print("\n[6] JSON 提取与字段清洗")
    from services.ai_analyzer import _extract_json
    check("纯 JSON", _extract_json('{"a": 1}') == {"a": 1})
    check("代码块 JSON", _extract_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("前后说明", _extract_json('结果如下：{"a": 1} 以上。') == {"a": 1})
    check("非法内容 None", _extract_json("没有 JSON") is None)
    check("数组不误判", _extract_json("[1,2]") is None)
    from services.ai_analyzer import _clamp_score, _clean_sentiment
    check("分数截断", _clamp_score(150) == 100.0 and _clamp_score(-999) == -100.0
          and _clamp_score("abc") is None)
    check("缺失摘要不产出", _clean_sentiment({"key_events": []}) is None)
    fallback = _clean_sentiment({"sentiment_score": "10", "summary": "s",
                                 "key_events": "not-a-list"})
    check("非法事件列表容错", fallback["key_events"] == []
          and fallback["distribution"] == {"positive": 0, "negative": 0, "neutral": 0})


# ---------------------------------------------------------------------------
# 7. ReportBuilder 集成
# ---------------------------------------------------------------------------

class _StubAnalyzer:
    """成功路径 stub: 返回固定情绪与综合点评。"""

    instances = 0

    def __init__(self, *args, **kwargs):
        _StubAnalyzer.instances += 1
        self.available = True
        self.provider = "stub"
        self.model = "stub-1"
        self.last_error = None

    def analyze_news_sentiment(self, news_list, stock_name="", code=""):
        return {"overall_sentiment": "positive", "sentiment_score": 42.5,
                "key_events": [{"event": "业绩增长", "impact": "利好基本面",
                                "sentiment": "positive"}],
                "summary": "新闻整体偏正面。",
                "distribution": {"positive": 1, "negative": 0, "neutral": 0}}

    def generate_analysis_report(self, stock_data):
        return {"summary": "AI 综合总结", "technical_comment": "技术点评",
                "fundamental_comment": "基本面点评", "risks": ["风险1", "风险2"],
                "catalysts": ["催化1"], "recommendation": "谨慎参与"}


class _FailAnalyzer(_StubAnalyzer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_error = {"category": "timeout", "message": "LLM 请求超时"}

    def analyze_news_sentiment(self, news_list, stock_name="", code=""):
        return None

    def generate_analysis_report(self, stock_data):
        return None


def _run_report(code="600519"):
    from services.report_builder import ReportBuilder
    events = list(ReportBuilder().build_report(code))
    final = [e for e in events if e["stage"] == "report"][-1]["report"]
    return events, final


def test_report_without_ai():
    print("\n[7] 报告: 未配置 AI → 50/50 降级")
    import services.llm_config as llm_config
    llm_config._cache = None  # 确保未配置
    events, report = _run_report()
    check("报告成功产出", "error" not in report and report.get("stock_info", {}).get("name"),
          str(report.get("error")))
    check("评级权重 50/50", report["rating"]["weights"]["technical"] == 0.5
          and report["rating"]["weights"]["sentiment"] is None,
          str(report["rating"]["weights"]))
    check("标注 AI 不可用", "AI 分析不可用" in (report["news_sentiment"]["note"] or ""),
          report["news_sentiment"]["note"])
    check("ai_report 为 null", report["ai_report"] is None)
    check("ai_meta 不可用", report["ai_meta"]["available"] is False)
    check("权重和=1", abs(report["rating"]["weights"]["technical"] * 2 - 1.0) < 1e-9)
    stages = [e["stage"] for e in events]
    check("SSE 阶段序列", stages[:4] == ["fetching_data", "technical_analysis",
                                    "fundamental_analysis", "ai_analysis"]
          and stages[-1] == "report", str(stages))
    check("新闻列表仍透传", isinstance(report["news_sentiment"]["news_list"], list)
          and len(report["news_sentiment"]["news_list"]) > 0)
    check("免责声明", "不构成投资建议" in (report.get("disclaimer") or ""))


def test_report_with_ai():
    print("\n[8] 报告: AI 成功 → 35/35/30")
    import services.report_builder as rb
    original = rb.AIAnalyzer
    rb.AIAnalyzer = _StubAnalyzer
    try:
        events, report = _run_report()
    finally:
        rb.AIAnalyzer = original
    weights = report["rating"]["weights"]
    check("评级权重 35/35/30", weights["technical"] == 0.35
          and weights["fundamental"] == 0.35 and weights["sentiment"] == 0.30,
          str(weights))
    check("情绪分入评分", report["rating"]["sentiment_score"] == 42.5,
          str(report["rating"]["sentiment_score"]))
    check("新闻情绪块填充", report["news_sentiment"]["overall"] == "positive"
          and report["news_sentiment"]["score"] == 42.5
          and len(report["news_sentiment"]["key_events"]) == 1,
          str(report["news_sentiment"])[:160])
    check("情绪分布透传", report["news_sentiment"]["distribution"]["positive"] == 1)
    check("AI 综合报告填充", report["ai_report"] is not None
          and report["ai_report"]["summary"] == "AI 综合总结")
    check("ai_meta 记录 provider", report["ai_meta"]["available"] is True
          and report["ai_meta"]["provider"] == "stub")
    check("综合分按权重计算", abs(report["rating"]["score"] - round(
        report["technical"]["score"] * 0.35 + report["fundamental"]["score"] * 0.35
        + 42.5 * 0.30, 2)) < 0.02, str(report["rating"]["score"]))
    ai_events = [e for e in events if e["stage"] == "ai_analysis"]
    check("AI 进度事件消息", len(ai_events) >= 3
          and any("新闻情绪" in e["message"] for e in ai_events), str(ai_events))


def test_report_ai_failure():
    print("\n[9] 报告: AI 失败 → 降级 + 警告")
    import services.report_builder as rb
    original = rb.AIAnalyzer
    rb.AIAnalyzer = _FailAnalyzer
    try:
        _, report = _run_report()
    finally:
        rb.AIAnalyzer = original
    check("失败回退 50/50", report["rating"]["weights"]["sentiment"] is None,
          str(report["rating"]["weights"]))
    check("报告仍产出", report["rating"]["score"] is not None)
    check("失败标注", "失败" in (report["news_sentiment"]["note"] or ""),
          report["news_sentiment"]["note"])
    check("警告透传", any("AI" in w or "失败" in w for w in report["data_meta"]["warnings"]),
          str(report["data_meta"]["warnings"])[:200])
    check("ai_meta 记录错误", len(report["ai_meta"]["errors"]) >= 1,
          str(report["ai_meta"]))


def test_report_ai_without_news():
    print("\n[10] 报告: 有 AI 但无新闻 → 不计入情绪分")
    import pandas as pd
    import services.report_builder as rb
    from services.data_fetcher import get_data_fetcher

    fetcher = get_data_fetcher()
    original_news = fetcher.get_stock_news
    original = rb.AIAnalyzer
    fetcher.get_stock_news = lambda code: pd.DataFrame(
        columns=["title", "content", "pub_time", "source"])
    rb.AIAnalyzer = _StubAnalyzer
    try:
        _, report = _run_report()
    finally:
        fetcher.get_stock_news = original_news
        rb.AIAnalyzer = original
    check("无新闻不参与加权", report["rating"]["weights"]["sentiment"] is None,
          str(report["rating"]["weights"]))
    check("无新闻标注", "无可靠关联新闻" in (report["news_sentiment"]["note"] or ""),
          report["news_sentiment"]["note"])
    check("AI 综合报告仍生成", report["ai_report"] is not None)


# ---------------------------------------------------------------------------
# 11. 配置 API + 持仓 AI 建议端点
# ---------------------------------------------------------------------------

def test_apis():
    print("\n[11] 配置 API 与 AI 建议端点")
    from api import config as config_api
    from api import portfolio as portfolio_api
    from models.schemas import ConfigUpdateRequest, LLMTestRequest
    from sqlalchemy import select

    async def flow():
        checks = {}
        # -- 初始状态 ---------------------------------------------------
        resp = await config_api.get_config()
        checks["GET /api/config 结构"] = {"app", "llm", "llm_defaults"} <= set(
            resp.model_dump().keys())
        checks["初始未配置"] = resp.llm.available is False

        # -- 更新（写入加密密钥）---------------------------------------
        await config_api.put_config(ConfigUpdateRequest(
            llm_provider="claude", llm_api_key="sk-secret-abcdef123456",
            llm_api_base="", llm_model="claude-test-model"))
        resp = await config_api.get_config()
        checks["更新后可用"] = resp.llm.available is True
        checks["密钥掩码不回显"] = (resp.llm.api_key_configured is True
                              and resp.llm.api_key_masked == "sk-****3456"
                              and "sk-secret" not in resp.model_dump_json())
        checks["模型保存"] = resp.llm.model == "claude-test-model"
        checks["默认 base 补全"] = resp.llm.api_base == "https://api.anthropic.com"
        checks["来源标记 sqlite"] = resp.llm.sources.get("provider") == "sqlite"

        # -- 加密落库（DB 中无明文）------------------------------------
        from models.database import ConfigItem, get_session_factory
        async with get_session_factory()() as session:
            row = (await session.execute(select(ConfigItem).where(
                ConfigItem.key == "llm_api_key"))).scalar_one()
        checks["DB 密文非明文"] = "sk-secret-abcdef123456" not in row.value
        checks["DB 密文有前缀"] = row.value.startswith(("enc1:", "b64:"))

        # -- 非法 provider ---------------------------------------------
        bad_rejected = False
        try:
            await config_api.put_config(ConfigUpdateRequest(llm_provider="hacker"))
        except Exception as exc:
            bad_rejected = "400" in str(getattr(exc, "status_code", exc))
        checks["非法 provider 拒绝"] = bad_rejected

        # -- 关闭 AI ----------------------------------------------------
        await config_api.put_config(ConfigUpdateRequest(llm_provider="none",
                                                        clear_api_key=True))
        resp = await config_api.get_config()
        checks["关闭后不可用"] = resp.llm.available is False
        checks["密钥已清除"] = resp.llm.api_key_configured is False

        # -- 恢复配置供后续用例 -----------------------------------------
        await config_api.put_config(ConfigUpdateRequest(
            llm_provider="claude", llm_api_key="sk-secret-abcdef123456"))
        return checks

    checks = asyncio.run(flow())
    for name, ok in checks.items():
        check(name, ok)

    # -- test-llm 端点（stub 掉网络）-----------------------------------
    import api.config as config_module

    class _StubTester:
        def __init__(self, *a, **k):
            pass

        def test_connection(self, override=None):
            if override and override.get("provider") == "openai":
                return {"ok": False, "category": "auth", "error": "鉴权失败(401)",
                        "provider": "openai", "model": "gpt-4o-mini"}
            return {"ok": True, "provider": "claude", "model": "claude-test-model",
                    "latency_ms": 123, "reply": "OK"}

    original = config_module.AIAnalyzer
    config_module.AIAnalyzer = _StubTester
    try:
        ok_resp = asyncio.run(config_module.test_llm(LLMTestRequest()))
        bad_resp = asyncio.run(config_module.test_llm(
            LLMTestRequest(provider="openai", api_key="sk-bad-123456")))
    finally:
        config_module.AIAnalyzer = original
    check("test-llm 成功", ok_resp.ok is True and ok_resp.latency_ms == 123, str(ok_resp))
    check("test-llm 失败分类", bad_resp.ok is False and bad_resp.category == "auth",
          str(bad_resp))


def test_ai_advice_endpoint():
    print("\n[12] GET /api/portfolio/risk/ai-advice")
    import api.portfolio as portfolio_api
    import services.ai_analyzer as ai_module
    from api import config as config_api
    from models.schemas import ConfigUpdateRequest, HoldingCreate

    async def flow():
        checks = {}
        # 关闭 LLM，确保走"未配置"分支（不发起真实网络请求）
        await config_api.put_config(ConfigUpdateRequest(llm_provider="none",
                                                        clear_api_key=True))
        empty = await portfolio_api.portfolio_ai_advice()
        checks["无持仓提示"] = empty["available"] is False and "无持仓" in empty["note"]
        await portfolio_api.add_holding(HoldingCreate(stock_code="600519", quantity=100,
                                                     cost_price=1400.0))
        unconfigured = await portfolio_api.portfolio_ai_advice()
        checks["未配置提示"] = unconfigured["available"] is False
        checks["未配置原因"] = "未配置" in (unconfigured["note"] or "")
        return checks

    checks = asyncio.run(flow())
    for name, ok in checks.items():
        check(name, ok)

    # -- 配置 + stub 成功路径 -------------------------------------------
    class _StubAdvice:
        calls = 0

        def __init__(self, *a, **k):
            self.available = True
            self.provider = "stub"
            self.model = "stub-1"
            self.last_error = None

        def generate_portfolio_advice(self, data):
            _StubAdvice.calls += 1
            assert data["holdings"] and isinstance(data["risk_metrics"], dict)
            return {"overall_assessment": "组合总体可控", "risk_warnings": ["相关偏高"],
                    "suggestions": ["分散配置", "控制仓位"], "rebalance_ideas": ["降低集中度"]}

    original = ai_module.AIAnalyzer
    ai_module.AIAnalyzer = _StubAdvice
    portfolio_api._ai_advice_cache.update({"key": None, "at": 0.0, "payload": None})
    try:
        first = asyncio.run(portfolio_api.portfolio_ai_advice())
        second = asyncio.run(portfolio_api.portfolio_ai_advice())
        forced = asyncio.run(portfolio_api.portfolio_ai_advice(force=True))
    finally:
        ai_module.AIAnalyzer = original
    check("建议返回", first["available"] is True
          and first["advice"]["overall_assessment"] == "组合总体可控", str(first)[:160])
    check("含调仓思路", first["advice"]["rebalance_ideas"] == ["降低集中度"])
    check("风险等级透传", "risk_level" in first)
    check("缓存命中", second.get("cached") is True, str(second)[:120])
    check("force 绕过缓存", forced.get("cached") is not True and _StubAdvice.calls == 2,
          f"calls={_StubAdvice.calls}")


def test_ai_advice_failure():
    print("\n[13] AI 建议失败降级")
    import api.portfolio as portfolio_api
    import services.ai_analyzer as ai_module

    class _FailAdvice:
        def __init__(self, *a, **k):
            self.available = True
            self.provider = "stub"
            self.model = "stub-1"
            self.last_error = {"category": "timeout", "message": "LLM 请求超时"}

        def generate_portfolio_advice(self, data):
            return None

    original = ai_module.AIAnalyzer
    ai_module.AIAnalyzer = _FailAdvice
    portfolio_api._ai_advice_cache.update({"key": None, "at": 0.0, "payload": None})
    try:
        resp = asyncio.run(portfolio_api.portfolio_ai_advice())
    finally:
        ai_module.AIAnalyzer = original
    check("失败降级不抛错", resp["available"] is False)
    check("失败原因透传", "LLM 请求超时" in (resp["note"] or ""), resp.get("note"))


# ---------------------------------------------------------------------------
# 14. 生产模式静态托管
# ---------------------------------------------------------------------------

def test_spa_static():
    print("\n[14] SPA 静态托管（生产模式）")
    import tempfile as _tf

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from main import SPAStaticFiles

    dist = Path(_tf.mkdtemp(prefix="stockpanel_dist_"))
    (dist / "index.html").write_text("<html><body>StockPanel SPA</body></html>",
                                     encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")
    client = TestClient(app)
    check("根路径返回 index", client.get("/").status_code == 200
          and "StockPanel SPA" in client.get("/").text)
    check("前端路由回退 index", client.get("/portfolio").status_code == 200
          and "StockPanel SPA" in client.get("/portfolio").text)
    check("静态资源直出", client.get("/assets/app.js").status_code == 200)
    check("API 路由优先", client.get("/api/health").json() == {"status": "ok"})
    check("未知 API 不回退 html",
          client.get("/api/not-exist").status_code == 404)
    check("index.html 不缓存",
          client.get("/").headers.get("cache-control") == "no-cache")

    from config import settings
    if (settings.FRONTEND_DIST / "index.html").is_file():
        from main import app as real_app
        mounts = [r for r in real_app.routes if getattr(r, "name", "") == "frontend"]
        check("真实 dist 已挂载", len(mounts) == 1)
    else:
        print("  - 真实 frontend/dist 尚未构建，跳过真实挂载检查")


def main() -> int:
    asyncio.run(init_db())
    test_prompts()
    test_secret_box()
    test_config_resolution()
    test_analyzer_protocol()
    test_analyzer_degradation()
    test_json_extraction()
    test_report_without_ai()
    test_report_with_ai()
    test_report_ai_failure()
    test_report_ai_without_news()
    test_apis()
    test_ai_advice_endpoint()
    test_ai_advice_failure()
    test_spa_static()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败  (临时数据目录: {_TMP})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
