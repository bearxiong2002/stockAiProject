"""ScoringEngine — 综合评分引擎（阶段 4.3）。

按 design.md 4.5:
- 有 AI 情绪分: 综合 = 技术×0.35 + 基本面×0.35 + AI×0.30
- 无 AI（未配置 Key 或调用失败）: 综合 = 技术×0.50 + 基本面×0.50
评级映射见 4.5.2（星级/标签/建议操作/颜色）。
"""
from __future__ import annotations

# (score 下界, 星级, 标签, 建议操作, 颜色)
RATING_TABLE: list[tuple[float, str, str, str, str]] = [
    (60, "★★★★★", "强烈推荐", "可积极建仓", "deep_red"),
    (30, "★★★★", "推荐", "可适量买入", "red"),
    (10, "★★★", "谨慎推荐", "可少量参与", "orange"),
    (-9, "★★", "中性", "观望为主", "gray"),
    (-39, "★", "不推荐", "建议回避", "green"),
    (-100, "卖出", "建议清仓", "建议清仓", "deep_green"),
]

DISCLAIMER = "本分析仅供参考，不构成投资建议，投资有风险，入市需谨慎"


def _star_table_fallback(score: float) -> tuple[str, str, str, str]:
    """-39~-10 与 -100~-40 区间的星级（design 表中"卖出"行无星级）。"""
    return ("★", "不推荐", "建议回避", "green") if score >= -39 else \
        ("卖出", "建议清仓", "建议清仓", "deep_green")


class ScoringEngine:
    """综合评分合成与投资评级映射。"""

    def calculate_rating(self, tech_score: float | None, fund_score: float | None,
                         sentiment_score: float | None = None) -> dict:
        """技术/基本面分数合成综合评分并映射评级。

        sentiment_score 为 None（AI 不可用）时回退 50/50 权重。
        任一核心分数缺失时不产出完整评级（score=None）。
        """
        if tech_score is None or fund_score is None:
            return {
                "score": None, "level": None, "label": None,
                "action": None, "color": None,
                "weights": None,
                "sentiment_score": sentiment_score,
                "note": "技术面或基本面数据不足，无法产出完整评级",
            }
        if sentiment_score is None:
            weights = {"technical": 0.50, "fundamental": 0.50, "sentiment": None}
            score = tech_score * 0.50 + fund_score * 0.50
        else:
            weights = {"technical": 0.35, "fundamental": 0.35, "sentiment": 0.30}
            score = tech_score * 0.35 + fund_score * 0.35 + sentiment_score * 0.30
        score = round(max(-100.0, min(100.0, score)), 2)
        for lower, level, label, action, color in RATING_TABLE:
            # 行命中条件 score >= lower 已含边界语义（-39 属 ★，-40 属 卖出）
            if score >= lower:
                return {
                    "score": score,
                    "level": level,
                    "label": label,
                    "action": action,
                    "color": color,
                    "weights": weights,
                    "sentiment_score": sentiment_score,
                }
        level, label, action, color = _star_table_fallback(score)
        return {"score": score, "level": level, "label": label,
                "action": action, "color": color, "weights": weights,
                "sentiment_score": sentiment_score}
