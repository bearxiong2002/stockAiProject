import { Card, Typography } from 'antd'
import ScoreGauge from '@/components/charts/ScoreGauge'
import type { StockReport } from '@/types'

const RATING_COLORS: Record<string, string> = {
  deep_red: '#8c1f1b', red: '#e0524d', orange: '#e6a23c',
  gray: 'var(--text-secondary)', green: '#2eab68', deep_green: '#1a6b41'
}

function colorOf(rating: { color?: string | null; score?: number | null }): string {
  return RATING_COLORS[rating.color ?? ''] ?? 'var(--text-secondary)'
}

/** ① 头部概览: 名称/代码/行业 + 价格涨跌幅 + 综合评级大字 + 三个子分仪表盘。 */
export default function HeaderCard({ report }: { report: StockReport }) {
  const info = report.stock_info
  const rating = report.rating
  const pct = info.pct_change
  return (
    <Card size="small" styles={{ body: { padding: '14px 18px' } }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 240 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <strong style={{ fontSize: 20 }}>{info.name}</strong>
            <Typography.Text code>{info.code}</Typography.Text>
            {info.industry && <Typography.Text type="secondary">{info.industry}</Typography.Text>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 8 }}>
            <span style={{ fontSize: 26, fontWeight: 700 }}>{info.latest_price?.toFixed(2)}</span>
            {pct != null && (
              <span style={{ color: pct >= 0 ? '#e0524d' : '#2eab68', fontSize: 14 }}>
                {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
              </span>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {info.trade_date}
            </Typography.Text>
          </div>
          <div style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 11 }}>
            生成时间 {report.generated_at?.replace('T', ' ').slice(0, 19)}
          </div>
        </div>
        <div style={{ textAlign: 'center', minWidth: 170 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 2 }}>综合评级</div>
          <div style={{ color: colorOf(rating), fontWeight: 700 }}>
            <div style={{ fontSize: 30, lineHeight: 1.2 }}>{rating.level}</div>
            <div style={{ fontSize: 15 }}>
              {rating.label}
              {rating.score != null && (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', marginLeft: 8 }}>
                  {rating.score > 0 ? '+' : ''}{rating.score.toFixed(1)}
                </span>
              )}
            </div>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 4 }}>
            {rating.action}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <ScoreGauge small width={130} label="技术面" score={report.technical?.score} />
          <ScoreGauge small width={130} label="基本面" score={report.fundamental?.score} />
          <ScoreGauge small width={130} label="AI情绪" score={report.rating?.sentiment_score} />
        </div>
      </div>
    </Card>
  )
}
