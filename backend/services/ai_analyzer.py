"""AIAnalyzer — LLM 分析服务（design.md §4.4，阶段8）。

职责:
- 新闻情绪分析 / 个股综合点评 / 持仓诊断建议；Prompt 模板见 config/prompts/
- 支持 claude（Anthropic Messages API）与 openai/custom（OpenAI 兼容 Chat Completions）
- 任何失败（未配置、鉴权、超时、网络、返回非法 JSON）都返回 None，由上层降级为
  纯规则分析，不阻塞报告生成（design §11.2）

同步实现: 报告生成器与 API 都在工作线程/事件循环外调用，复用 httpx 同步客户端；
测试可通过 transport 注入 httpx.MockTransport 离线验证。
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from config import settings
from services.llm_config import get_llm_config, public_llm_view, resolve_llm_config

logger = logging.getLogger("stockpanel.ai")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"

MAX_NEWS_ITEMS = 10
MAX_NEWS_CONTENT_CHARS = 220
MAX_LIST_ITEMS = 6

# 情绪词映射（容忍模型输出中文标签）
_SENTIMENT_ALIASES = {
    "positive": "positive", "利好": "positive", "积极": "positive", "正面": "positive",
    "negative": "negative", "利空": "negative", "消极": "negative", "负面": "negative",
    "neutral": "neutral", "中性": "neutral", "无明显倾向": "neutral",
}

_PROMPT_CACHE: dict[str, str] = {}


class AIError(Exception):
    """LLM 调用错误（带分类，便于 /test-llm 与日志定位）。"""

    def __init__(self, category: str, message: str, *, status: int | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status = status

    def to_dict(self) -> dict:
        out = {"category": self.category, "message": self.message}
        if self.status is not None:
            out["status"] = self.status
        return out


# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

def load_prompt(name: str) -> str:
    """读取 Prompt 模板（带缓存）。缺失时抛 FileNotFoundError。"""
    if name not in _PROMPT_CACHE:
        path = PROMPTS_DIR / f"{name}.txt"
        _PROMPT_CACHE[name] = path.read_text(encoding="utf-8")
    return _PROMPT_CACHE[name]


_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_prompt(template: str, variables: dict[str, str]) -> str:
    """替换模板中的 {variable} 占位符；未提供的占位符原样保留。

    不用 str.format: 模板中包含 JSON 示例花括号，format 会误解析。
    """
    return _PLACEHOLDER.sub(
        lambda m: variables.get(m.group(1), m.group(0)), template)


# ---------------------------------------------------------------------------
# 上下文文本构造
# ---------------------------------------------------------------------------

def _fmt_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num != num:  # NaN
        return "—"
    return f"{num:.{digits}f}{suffix}"


def format_news_list(news_list: list[dict]) -> str:
    """新闻列表 → 带编号的紧凑文本（标题 + 摘要 + 来源时间）。"""
    lines: list[str] = []
    for i, item in enumerate(news_list[:MAX_NEWS_ITEMS], start=1):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        content = str(item.get("content") or "").strip().replace("\n", " ")
        if len(content) > MAX_NEWS_CONTENT_CHARS:
            content = content[:MAX_NEWS_CONTENT_CHARS] + "…"
        meta = " | ".join(x for x in (str(item.get("source") or "").strip(),
                                      str(item.get("pub_time") or "").strip()) if x)
        lines.append(f"{i}. {title}" + (f"（{meta}）" if meta else "")
                     + (f"\n   摘要: {content}" if content else ""))
    return "\n".join(lines) if lines else "（无新闻数据）"


def format_stock_context(stock_data: dict) -> str:
    """个股量化结果 → 供 LLM 阅读的结构化文本。"""
    info = stock_data.get("stock_info") or {}
    tech = stock_data.get("technical_result") or {}
    fund = stock_data.get("fundamental_result") or {}
    flow = stock_data.get("fund_flow") or {}
    kline = stock_data.get("kline_summary") or {}
    lines = [
        f"最新价: {_fmt_num(info.get('latest_price'))}  涨跌幅: {_fmt_num(info.get('pct_change'), 2, '%')}"
        f"  市值(亿): {_fmt_num(info.get('market_cap'), 1)}  数据日期: {info.get('trade_date') or '—'}",
        f"综合评分: {_fmt_num((stock_data.get('rating') or {}).get('score'), 1)}"
        f"  评级: {(stock_data.get('rating') or {}).get('label') or '—'}"
        f"  评分权重: {(stock_data.get('rating') or {}).get('weights') or '—'}",
        f"技术面: 得分 {_fmt_num(tech.get('score'), 1)}（{tech.get('rating') or '—'}）",
    ]
    for key, label in (("trend", "趋势"), ("oscillator", "震荡"), ("channel", "通道"),
                       ("volume", "量能")):
        comp = (tech.get("components") or {}).get(key) or {}
        if comp:
            lines.append(f"  - {label}: {_fmt_num(comp.get('score'), 0)}")
    signals = tech.get("signals") or []
    if signals:
        top = "；".join(str(s.get("signal") or s.get("note") or "")
                        for s in signals[:MAX_LIST_ITEMS])
        lines.append(f"  技术信号: {top}")
    lines.append(
        f"基本面: 得分 {_fmt_num(fund.get('score'), 1)}（{fund.get('rating') or '—'}）"
        + f"  数据完整: {'是' if not fund.get('incomplete') else '否（存在缺口）'}")
    for key, label in (("valuation", "估值"), ("growth", "成长"), ("health", "健康度")):
        sub = fund.get(key) or {}
        if sub:
            items = "；".join(
                f"{it.get('name')}={_fmt_num(it.get('value'))}"
                + (f"(行业中值 {_fmt_num(it.get('industry_median'))})"
                   if it.get("industry_median") is not None else "")
                for it in (sub.get("items") or [])[:4])
            lines.append(f"  - {label}: 得分 {_fmt_num(sub.get('score'), 0)}  {items}")
    if flow:
        lines.append(
            f"资金流: 近5日主力净额 {_fmt_num(flow.get('main_net_inflow_5d'), 2)}"
            f"（{'净流入' if flow.get('trend') == 'inflow' else '净流出' if flow.get('trend') == 'outflow' else '未知'}）")
    if kline:
        lines.append(
            f"价格位置: 收盘 {_fmt_num(kline.get('close'))}  MA5 {_fmt_num(kline.get('ma_5'))}"
            f"  MA20 {_fmt_num(kline.get('ma_20'))}  MA60 {_fmt_num(kline.get('ma_60'))}"
            f"  近20日涨跌 {_fmt_num(kline.get('pct_20d'), 2, '%')}"
            f"  近60日涨跌 {_fmt_num(kline.get('pct_60d'), 2, '%')}")
    warnings = stock_data.get("warnings") or []
    if warnings:
        lines.append("数据提示: " + "；".join(str(w) for w in warnings[:4]))
    return "\n".join(lines)


def format_sentiment_context(sentiment: dict | None) -> str:
    if not sentiment or sentiment.get("score") is None:
        return "（无可靠的新闻情绪结果，请勿据此推断新闻面）"
    events = sentiment.get("key_events") or []
    event_text = "；".join(
        f"{e.get('event')}（{e.get('sentiment')}）" for e in events[:MAX_LIST_ITEMS])
    return (f"整体倾向: {sentiment.get('overall') or '—'}  情绪分: "
            f"{_fmt_num(sentiment.get('score'), 1)}\n摘要: {sentiment.get('summary') or '—'}"
            + (f"\n关键事件: {event_text}" if event_text else ""))


def format_portfolio_context(portfolio_data: dict) -> tuple[str, str, str]:
    """持仓数据 → (持仓明细, 风险指标, 行业分布) 三段文本。"""
    holdings = portfolio_data.get("holdings") or []
    h_lines = []
    for h in holdings:
        h_lines.append(
            f"{h.get('stock_name') or ''}({h.get('stock_code')})"
            f" 数量 {h.get('quantity')}  成本 {_fmt_num(h.get('cost_price'))}"
            f"  现价 {_fmt_num(h.get('latest_price'))}"
            f"  盈亏 {_fmt_num(h.get('profit_pct'), 2, '%')}"
            f"  占比 {_fmt_num(h.get('weight'), 2, '%')}"
            f"  行业 {h.get('industry') or '—'}")
    holdings_text = "\n".join(h_lines) if h_lines else "（无持仓）"

    risk = portfolio_data.get("risk_metrics") or {}
    r_lines: list[str] = []
    if risk.get("total_market_value") is not None:
        r_lines.append(f"组合市值: {_fmt_num(risk.get('total_market_value'), 0)} 元"
                       f"  样本天数: {risk.get('sample_days') or '—'}")
    var = risk.get("var") or {}
    if var:
        r_lines.append(f"VaR95(单日): {_fmt_num((var.get('95') or {}).get('pct'), 2, '%')}"
                       f"  VaR99: {_fmt_num((var.get('99') or {}).get('pct'), 2, '%')}")
    dd = risk.get("max_drawdown") or {}
    if dd:
        r_lines.append(f"最大回撤: {_fmt_num(dd.get('max'), 2, '%')}"
                       f"（{dd.get('start') or '—'} ~ {dd.get('end') or '—'}）"
                       f"  当前回撤: {_fmt_num(dd.get('current'), 2, '%')}")
    vol = risk.get("volatility") or {}
    if vol:
        r_lines.append(f"年化波动率: 组合 {_fmt_num(vol.get('portfolio'), 2, '%')}"
                       f" / 沪深300 {_fmt_num(vol.get('index'), 2, '%')}")
    if risk.get("beta") is not None:
        r_lines.append(f"Beta(vs 沪深300): {_fmt_num(risk.get('beta'), 2)}")
    if risk.get("sharpe") is not None:
        r_lines.append(f"夏普比率: {_fmt_num(risk.get('sharpe'), 2)}")
    conc = risk.get("concentration") or {}
    if conc:
        r_lines.append(f"集中度: {conc.get('level') or '—'}（HHI {conc.get('hhi')}，"
                       f"前3大占比 {_fmt_num(conc.get('top3_pct'), 2, '%')}，"
                       f"持仓 {conc.get('count')} 只）")
    corr = risk.get("correlation") or {}
    if corr.get("high_pairs"):
        pairs = "；".join(f"{p['pair'][0]}↔{p['pair'][1]} {_fmt_num(p.get('corr'))}"
                          for p in corr["high_pairs"][:4])
        r_lines.append(f"高相关持仓对: {pairs}")
    if risk.get("risk_level"):
        r_lines.append(f"风险等级: {risk.get('risk_level')}")
    for w in (risk.get("warnings") or [])[:3]:
        r_lines.append(f"风险提示: {w}")
    risk_text = "\n".join(r_lines) if r_lines else "（风险指标不可用）"

    sector = portfolio_data.get("sector_exposure") or {}
    sectors = sector.get("sectors") or []
    sector_text = "；".join(
        f"{s.get('industry')} {_fmt_num(s.get('weight_pct'), 2, '%')}"
        for s in sectors[:8]) if sectors else "（行业分布不可用）"
    return holdings_text, risk_text, sector_text


# ---------------------------------------------------------------------------
# AIAnalyzer
# ---------------------------------------------------------------------------

class AIAnalyzer:
    """LLM 分析服务；未配置或调用失败时方法返回 None（上层降级）。"""

    def __init__(self, config: dict | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._config = config or get_llm_config()
        self._transport = transport
        self.last_error: dict | None = None

    # -- 状态 ---------------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self._config.get("available"))

    @property
    def provider(self) -> str:
        return self._config.get("provider") or "none"

    @property
    def model(self) -> str:
        return self._config.get("model") or ""

    def config_view(self) -> dict:
        return public_llm_view(self._config)

    # -- 对外开放能力 -------------------------------------------------------

    def analyze_news_sentiment(self, news_list: list[dict], stock_name: str = "",
                               code: str = "") -> dict | None:
        """新闻情绪分析；输入 [{title, content, pub_time, source}, ...]。"""
        if not news_list:
            self.last_error = AIError("no_input", "无新闻数据，跳过情绪分析").to_dict()
            return None
        variables = {
            "stock_name": stock_name,
            "code": code,
            "today": time.strftime("%Y-%m-%d"),
            "news_text": format_news_list(news_list),
        }
        data = self._chat_json("news_sentiment", variables)
        if data is None:
            return None
        return _clean_sentiment(data)

    def generate_analysis_report(self, stock_data: dict) -> dict | None:
        """个股综合分析（技术/基本面/新闻情绪点评 + 风险 + 催化）。"""
        info = stock_data.get("stock_info") or {}
        variables = {
            "stock_name": str(info.get("name") or ""),
            "code": str(info.get("code") or ""),
            "today": time.strftime("%Y-%m-%d"),
            "stock_context": format_stock_context(stock_data),
            "sentiment_context": format_sentiment_context(stock_data.get("news_sentiment")),
        }
        data = self._chat_json("stock_report", variables)
        if data is None:
            return None
        return _clean_report(data)

    def generate_portfolio_advice(self, portfolio_data: dict) -> dict | None:
        """持仓诊断建议。"""
        holdings_text, risk_text, sector_text = format_portfolio_context(portfolio_data)
        variables = {
            "today": time.strftime("%Y-%m-%d"),
            "holdings_text": holdings_text,
            "risk_text": risk_text,
            "sector_text": sector_text,
        }
        data = self._chat_json("portfolio_advice", variables)
        if data is None:
            return None
        return _clean_advice(data)

    def test_connection(self, override: dict | None = None) -> dict:
        """连接测试: 最小 ping 请求，返回 {ok, provider, model, latency_ms, ...}。"""
        cfg = self._config
        if override:
            merged = dict(cfg)
            for key in ("provider", "api_key", "api_base", "model"):
                value = override.get(key)
                if value is not None and str(value).strip():
                    merged[key] = str(value).strip()
            if override.get("provider"):
                merged["provider"] = str(override["provider"]).strip().lower()
            merged["api_base"] = merged.get("api_base") or ""
            merged["model"] = merged.get("model") or ""
            cfg = resolve_llm_config(merged)
        tester = AIAnalyzer(cfg, transport=self._transport)
        if not tester.available:
            return {"ok": False, "category": "not_configured",
                    "error": tester._config.get("disabled_reason") or "LLM 未配置",
                    "provider": tester.provider, "model": tester.model}
        started = time.monotonic()
        try:
            reply = tester._chat(
                system="你是连接测试助手。",
                user="请只回复两个字符：OK",
                max_tokens=16, temperature=0.0)
        except AIError as exc:
            return {"ok": False, "category": exc.category, "error": exc.message,
                    "provider": tester.provider, "model": tester.model}
        return {"ok": True, "provider": tester.provider, "model": tester.model,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "reply": reply.strip()[:100]}

    # -- LLM 调用 -----------------------------------------------------------

    def _chat_json(self, prompt_name: str, variables: dict[str, str]) -> dict | None:
        """渲染模板 → 调用 LLM → 解析 JSON；失败记录 last_error 并返回 None。"""
        if not self.available:
            self.last_error = AIError(
                "not_configured",
                self._config.get("disabled_reason") or "LLM 未配置").to_dict()
            return None
        try:
            template = load_prompt(prompt_name)
        except OSError as exc:
            logger.error("Prompt 模板读取失败 %s: %s", prompt_name, exc)
            self.last_error = AIError("prompt_missing", f"模板缺失: {prompt_name}").to_dict()
            return None
        prompt = render_prompt(template, variables)
        try:
            text = self._chat(system="你是严谨的中文金融分析助手，只输出要求的 JSON。",
                              user=prompt)
        except AIError as exc:
            self.last_error = exc.to_dict()
            logger.warning("LLM 调用失败[%s] %s", prompt_name, exc.message)
            return None
        data = _extract_json(text)
        if data is None:
            self.last_error = AIError("bad_json", "模型返回内容不是合法 JSON").to_dict()
            logger.warning("LLM 返回无法解析为 JSON（%s）: %s", prompt_name, text[:200])
            return None
        self.last_error = None
        return data

    def _chat(self, *, system: str, user: str, max_tokens: int | None = None,
              temperature: float | None = None) -> str:
        """单轮对话；失败抛 AIError（含分类），成功返回纯文本。"""
        cfg = self._config
        provider = cfg.get("provider")
        api_key = cfg.get("api_key") or ""
        api_base = (cfg.get("api_base") or "").rstrip("/")
        model = cfg.get("model") or ""
        if not api_key:
            raise AIError("not_configured", "缺少 LLM API Key")
        if provider not in ("claude", "openai", "custom"):
            raise AIError("not_configured", f"未启用的 LLM provider: {provider}")
        if not api_base:
            raise AIError("not_configured", "缺少 API Base URL")

        max_tokens = max_tokens or settings.LLM_MAX_TOKENS
        temperature = settings.LLM_TEMPERATURE if temperature is None else temperature
        if provider == "claude":
            url = _join_url(api_base, "v1/messages")
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
            payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                       "system": system, "messages": [{"role": "user", "content": user}]}
        else:
            url = _join_url(api_base, "chat/completions")
            headers = {"Authorization": f"Bearer {api_key}",
                       "content-type": "application/json"}
            payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}
        timeout = httpx.Timeout(connect=settings.LLM_CONNECT_TIMEOUT,
                                read=settings.LLM_READ_TIMEOUT, write=15,
                                pool=settings.LLM_CONNECT_TIMEOUT)
        try:
            with httpx.Client(timeout=timeout, trust_env=settings.LLM_HTTP_TRUST_ENV,
                              verify=True, transport=self._transport) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise AIError("timeout", f"LLM 请求超时（{type(exc).__name__}）") from exc
        except httpx.HTTPError as exc:
            raise AIError("network", f"LLM 网络错误: {type(exc).__name__}") from exc

        if resp.status_code != 200:
            raise _http_error(resp, provider)
        try:
            body = resp.json()
        except ValueError as exc:
            raise AIError("bad_response", "LLM 响应非 JSON") from exc
        text = _extract_text(body, provider)
        if not text:
            raise AIError("bad_response", "LLM 响应缺少文本内容")
        return text


def _join_url(base: str, path: str) -> str:
    if base.endswith("/" + path):
        return base
    return f"{base}/{path}"


def _extract_text(body: dict, provider: str) -> str:
    """按 provider 提取回复文本。"""
    if provider == "claude":
        blocks = body.get("content") or []
        return "".join(str(b.get("text") or "") for b in blocks
                       if isinstance(b, dict) and b.get("type") in (None, "text"))
    choices = body.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # 兼容部分兼容层的分段格式
            return "".join(str(c.get("text") or "") for c in content if isinstance(c, dict))
        return str(content or "")
    return ""


def _http_error(resp: httpx.Response, provider: str) -> AIError:
    status = resp.status_code
    message = ""
    try:
        body = resp.json()
        err = body.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or "")
        elif err:
            message = str(err)
        message = message or str(body.get("message") or "")[:200]
    except ValueError:
        message = (resp.text or "")[:200]
    if status in (401, 403):
        return AIError("auth", f"鉴权失败({status}): {message or '请检查 API Key'}", status=status)
    if status == 404:
        return AIError("model_not_found",
                       f"模型或地址不存在(404): {message or '请检查模型名/API Base'}", status=status)
    if status == 429:
        return AIError("rate_limit", f"触发限流(429): {message or '请稍后重试'}", status=status)
    if status == 400 and "model" in message.lower():
        return AIError("model_not_found", f"模型不可用(400): {message}", status=status)
    if status in (502, 503, 504):
        detail = (f"（{message}）" if message
                  else "（上游或代理不可达，请检查 API Base、网络与代理设置）")
        return AIError("http_error", f"LLM 服务不可用({status}){detail}", status=status)
    detail = f": {message}" if message else "（响应无说明内容）"
    return AIError("http_error", f"LLM 服务返回 {status}{detail}", status=status)


def _extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象（容忍 ```json 代码块与前后说明文字）。"""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.S)
    if fence:
        stripped = fence.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _as_text(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:limit]


def _as_list(value: Any, limit: int = MAX_LIST_ITEMS, item_limit: int = 120) -> list:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if isinstance(item, dict):
            out.append({k: _as_text(v, item_limit) for k, v in item.items()
                        if isinstance(v, (str, int, float)) or v is None})
        else:
            text = _as_text(item, item_limit)
            if text:
                out.append(text)
    return out


def _normalize_sentiment(value: Any) -> str:
    return _SENTIMENT_ALIASES.get(str(value or "").strip().lower(), "neutral")


def _clamp_score(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:
        return None
    return round(max(-100.0, min(100.0, num)), 1)


def _clean_sentiment(data: dict) -> dict | None:
    score = _clamp_score(data.get("sentiment_score"))
    overall = _normalize_sentiment(data.get("overall_sentiment"))
    key_events = []
    for event in _as_list(data.get("key_events"), limit=5):
        if not isinstance(event, dict):
            continue
        name = _as_text(event.get("event"), 80)
        if not name:
            continue
        key_events.append({"event": name,
                           "impact": _as_text(event.get("impact"), 120),
                           "sentiment": _normalize_sentiment(event.get("sentiment"))})
    summary = _as_text(data.get("summary"), 400)
    if score is None and not summary:
        return None
    if score is None:
        score = 0.0
    distribution = {"positive": 0, "negative": 0, "neutral": 0}
    for event in key_events:
        distribution[event["sentiment"]] += 1
    return {
        "overall_sentiment": overall,
        "sentiment_score": score,
        "key_events": key_events,
        "summary": summary,
        "distribution": distribution,
    }


def _clean_report(data: dict) -> dict | None:
    summary = _as_text(data.get("summary"), 600)
    if not summary:
        return None
    return {
        "summary": summary,
        "technical_comment": _as_text(data.get("technical_comment"), 400),
        "fundamental_comment": _as_text(data.get("fundamental_comment"), 400),
        "risks": _as_list(data.get("risks"), limit=4),
        "catalysts": _as_list(data.get("catalysts"), limit=3),
        "recommendation": _as_text(data.get("recommendation"), 300),
    }


def _clean_advice(data: dict) -> dict | None:
    assessment = _as_text(data.get("overall_assessment"), 600)
    if not assessment:
        return None
    return {
        "overall_assessment": assessment,
        "risk_warnings": _as_list(data.get("risk_warnings"), limit=4),
        "suggestions": _as_list(data.get("suggestions"), limit=5),
        "rebalance_ideas": _as_list(data.get("rebalance_ideas"), limit=3),
    }
