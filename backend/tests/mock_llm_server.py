"""本地 Mock LLM 服务（OpenAI 兼容），用于端到端验证 AI 链路（离线，不消耗真实额度）。

运行:
    cd backend && .venv/bin/python tests/mock_llm_server.py [port]   # 默认 18999

配合设置页/配置接口使用:
    PUT /api/config {"llm_provider": "custom",
                     "llm_api_key": "mock-key",
                     "llm_api_base": "http://127.0.0.1:18999/v1",
                     "llm_model": "mock-model"}

按 Prompt 内容返回对应的结构化 JSON（新闻情绪 / 个股点评 / 持仓建议）。
仅用于开发与验收测试，不实现鉴权与并发。
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SENTIMENT = {
    "overall_sentiment": "positive",
    "sentiment_score": 38.5,
    "key_events": [
        {"event": "半年报营收与净利润双增长", "impact": "盈利改善，支撑估值", "sentiment": "positive"},
        {"event": "机构调研密集，产能利用率高位", "impact": "经营景气度维持", "sentiment": "positive"},
        {"event": "部分股东披露减持计划", "impact": "短期资金面承压", "sentiment": "negative"},
    ],
    "summary": "近期新闻以业绩增长与机构关注为主，整体偏正面；股东减持计划构成短期扰动，"
               "但未见基本面恶化信号。",
}
REPORT = {
    "summary": "公司基本面保持稳健、估值处于行业中枢附近，技术面中性偏弱、量能一般，"
               "综合评级为谨慎推荐，建议控制仓位、逢回调分批参与。",
    "technical_comment": "均线系统纠缠，MACD 于零轴附近反复，成交量未明显放大，短期方向不明。",
    "fundamental_comment": "盈利与营收保持增长，负债水平健康，估值相对行业中值略有溢价。",
    "risks": ["技术面趋势偏弱，跌破关键均线需减仓", "股东减持带来短期抛压",
              "行业景气度回落可能压制估值"],
    "catalysts": ["机构调研密集，关注度提升", "产能利用率维持高位"],
    "recommendation": "可少量参与并设置止损；若放量突破前高，可考虑加仓。",
}
ADVICE = {
    "overall_assessment": "组合整体风险可控，但持仓集中在单一行业，相关性偏高，"
                          "分散度不足，建议逐步均衡配置。",
    "risk_warnings": ["行业暴露集中，单一行业波动将显著影响组合", "持仓相关性偏高，分散效果有限"],
    "suggestions": ["将单一行业权重控制在 50% 以内", "为高波动持仓设置止损纪律",
                    "保留一定现金比例应对回撤"],
    "rebalance_ideas": ["逐步减配高相关持仓，增配低相关行业", "用指数基金替代部分个股仓位"],
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[mock-llm] " + fmt % args + "\n")

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith("/v1/models"):
            self._send({"object": "list", "data": [{"id": "mock-model", "object": "model"}]})
        else:
            self._send({"error": {"message": "not found"}}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode())
        except ValueError:
            self._send({"error": {"message": "bad json"}}, 400)
            return
        messages = body.get("messages") or []
        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        if "只回复两个字符" in prompt or "连接测试" in prompt:
            content = "OK"
        elif "overall_sentiment" in prompt:
            content = "```json\n" + json.dumps(SENTIMENT, ensure_ascii=False) + "\n```"
        elif "rebalance_ideas" in prompt:
            content = json.dumps(ADVICE, ensure_ascii=False)
        else:
            content = "分析结果:\n" + json.dumps(REPORT, ensure_ascii=False)
        self._send({
            "id": "chatcmpl-mock", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        })


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18999
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock LLM server on http://127.0.0.1:{port}/v1 (OpenAI 兼容)", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
