import { Card, Tag, Typography } from 'antd'
import {
  CloseCircleOutlined,
  RiseOutlined,
  ThunderboltOutlined
} from '@ant-design/icons'
import type { StockReport } from '@/types'

const UP = '#e0524d'
const DOWN = '#2eab68'

/** 规则兜底风险（AI 不可用时仍给出基于数据的提示）。 */
function ruleRisks(report: StockReport): string[] {
  const risks: string[] = []
  if ((report.technical?.score ?? 0) < -20) risks.push('技术面趋势偏弱，注意止损纪律')
  if ((report.fund_flow?.main_net_inflow_5d ?? 0) < 0) risks.push('近期主力资金净流出，关注承接力度')
  if (report.fundamental?.incomplete) risks.push('财务数据存在缺口，基本面结论可信度受限')
  if (report.data_meta?.warnings?.length) risks.push(...report.data_meta.warnings.slice(0, 3))
  return risks
}

/** ⑦ 综合分析: AI 总结/点评 + 风险（红） + 催化（绿） + 操作建议。 */
export default function ConclusionCard({ report }: { report: StockReport }) {
  const ai = report.ai_report
  const risks = ai?.risks?.length ? ai.risks : ruleRisks(report)
  const catalysts = ai?.catalysts ?? []
  const aiAvailable = !!report.ai_meta?.available

  return (
    <Card
      size="small"
      title="综合分析"
      styles={{ body: { padding: '12px 16px' } }}
      extra={
        ai ? (
          <Tag color="purple" style={{ fontSize: 10 }}>AI 生成</Tag>
        ) : (
          <Tag style={{ fontSize: 10 }}>
            {aiAvailable ? 'AI 调用失败，规则结论' : 'AI 未启用，规则结论'}
          </Tag>
        )
      }
    >
      <div style={{ fontSize: 13, lineHeight: 1.9 }}>
        {ai?.summary
          ?? report.summary
          ?? (report.error ? '报告生成失败' : '核心数据不足，暂不产出完整评级。')}
      </div>

      {(ai?.technical_comment || ai?.fundamental_comment) && (
        <div
          style={{
            marginTop: 10, padding: '8px 12px', borderRadius: 6,
            background: 'var(--bg-elevated)', fontSize: 12, lineHeight: 1.8
          }}
        >
          {ai?.technical_comment && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>技术面: </Typography.Text>
              {ai.technical_comment}
            </div>
          )}
          {ai?.fundamental_comment && (
            <div style={{ marginTop: 4 }}>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>基本面: </Typography.Text>
              {ai.fundamental_comment}
            </div>
          )}
        </div>
      )}

      {risks.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
            风险提示
          </div>
          {risks.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '3px 0' }}>
              <CloseCircleOutlined style={{ color: UP, marginTop: 3, fontSize: 12 }} />
              <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>{r}</span>
            </div>
          ))}
        </div>
      )}

      {catalysts.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
            潜在催化因素
          </div>
          {catalysts.map((c, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '3px 0' }}>
              <RiseOutlined style={{ color: DOWN, marginTop: 3, fontSize: 12 }} />
              <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>{c}</span>
            </div>
          ))}
        </div>
      )}

      {ai?.recommendation && (
        <div
          style={{
            marginTop: 12, padding: '8px 12px', borderRadius: 6,
            border: `1px solid ${UP}55`, fontSize: 12.5, lineHeight: 1.8
          }}
        >
          <ThunderboltOutlined style={{ color: UP, marginRight: 6 }} />
          <Typography.Text strong style={{ fontSize: 12 }}>操作建议: </Typography.Text>
          {ai.recommendation}
        </div>
      )}

      {!ai && (
        <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
          {report.news_sentiment?.note
            ?? 'AI 分析不可用：综合评分按技术面/基本面 50/50 权重，以上为规则结论'}
        </Typography.Text>
      )}
    </Card>
  )
}
