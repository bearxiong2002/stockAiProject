import { Card, Col, Empty, Row, Tag, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from '@/components/charts/chartTheme'
import type { SentimentKeyEvent, SentimentLabel, StockReport } from '@/types'

const SENTIMENT_META: Record<SentimentLabel, { text: string; color: string }> = {
  positive: { text: '利好', color: '#e0524d' },
  negative: { text: '利空', color: '#2eab68' },
  neutral: { text: '中性', color: '#8b93a1' }
}

function overallMeta(overall: string | null | undefined) {
  if (overall === 'positive') return SENTIMENT_META.positive
  if (overall === 'negative') return SENTIMENT_META.negative
  return SENTIMENT_META.neutral
}

/** ⑥ AI 新闻情绪: 情绪分布饼图 + 关键事件 + AI 摘要 + 新闻列表。 */
export default function SentimentCard({ report }: { report: StockReport }) {
  const s = report.news_sentiment
  const tokens = useChartTokens()
  const overall = overallMeta(s.overall)
  const distribution = s.distribution
  const hasDistribution = !!distribution &&
    distribution.positive + distribution.negative + distribution.neutral > 0
  const pieOption: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: tokens.tooltipBg,
      borderColor: tokens.tooltipBorder,
      textStyle: { color: tokens.tooltipText, fontSize: 11 }
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '50%'],
        label: { color: tokens.axisLabel, fontSize: 10, formatter: '{b} {c}' },
        data: [
          { name: '利好', value: distribution?.positive ?? 0, itemStyle: { color: '#e0524d' } },
          { name: '利空', value: distribution?.negative ?? 0, itemStyle: { color: '#2eab68' } },
          { name: '中性', value: distribution?.neutral ?? 0, itemStyle: { color: tokens.neutral } }
        ]
      }
    ]
  }

  return (
    <Card
      size="small"
      title="AI 新闻情绪"
      styles={{ body: { padding: '12px 16px' } }}
      extra={
        report.ai_meta?.available ? (
          <Tag color="purple" style={{ fontSize: 10 }}>
            {report.ai_meta.provider}/{report.ai_meta.model}
          </Tag>
        ) : (
          <Tag style={{ fontSize: 10 }}>AI 未启用</Tag>
        )
      }
    >
      {s.score != null ? (
        <>
          <Row gutter={8} align="middle">
            <Col xs={24} md={hasDistribution ? 14 : 24}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={{ fontSize: 22, fontWeight: 700, color: overall.color }}>
                  {overall.text}
                </span>
                <span style={{ fontSize: 16, fontWeight: 600, color: overall.color }}>
                  {s.score > 0 ? '+' : ''}{s.score.toFixed(1)}
                </span>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  情绪分（-100 ~ +100）
                </Typography.Text>
              </div>
              {s.summary && (
                <div style={{ fontSize: 12.5, lineHeight: 1.8, marginTop: 8 }}>
                  {s.summary}
                </div>
              )}
            </Col>
            {hasDistribution && (
              <Col xs={24} md={10}>
                <div style={{ height: 150 }}>
                  <ReactECharts option={pieOption} style={{ height: '100%', width: '100%' }}
                    notMerge lazyUpdate />
                </div>
              </Col>
            )}
          </Row>
          {s.key_events?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
                关键事件
              </div>
              {s.key_events.map((ev: SentimentKeyEvent, i: number) => {
                const meta = SENTIMENT_META[ev.sentiment] ?? SENTIMENT_META.neutral
                return (
                  <div
                    key={i}
                    style={{
                      display: 'flex', gap: 8, alignItems: 'flex-start',
                      borderBottom: '1px solid var(--border-color)', padding: '6px 0'
                    }}
                  >
                    <Tag color={meta.color} style={{ marginTop: 1, fontSize: 10 }}>
                      {meta.text}
                    </Tag>
                    <div style={{ fontSize: 12 }}>
                      <div>{ev.event}</div>
                      {ev.impact && (
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          {ev.impact}
                        </Typography.Text>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      ) : (
        <div
          style={{
            fontSize: 12, padding: '6px 10px', marginBottom: 10, borderRadius: 6,
            background: 'var(--bg-elevated)', color: 'var(--text-secondary)'
          }}
        >
          {s.note ?? '未配置 AI 分析，新闻情绪不计入综合评分（权重回退 50/50）'}
        </div>
      )}

      {s.news_list?.length ? (
        <div style={{ marginTop: s.score != null ? 12 : 0 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 2 }}>
            相关新闻（{s.news_list.length}）
          </div>
          {s.news_list.map((n, i) => (
            <div key={i} style={{ borderBottom: '1px solid var(--border-color)', padding: '6px 0', fontSize: 12 }}>
              <div>{n.title}</div>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                {n.source ?? ''} {n.pub_time?.slice(0, 16)}
              </Typography.Text>
            </div>
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无相关新闻"
          style={{ marginTop: s.score != null ? 10 : 0 }} />
      )}
    </Card>
  )
}
