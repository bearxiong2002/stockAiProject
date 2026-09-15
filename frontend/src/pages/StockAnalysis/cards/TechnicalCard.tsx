import { Card, Typography } from 'antd'
import type { StockReport } from '@/types'

const COMP_LABELS: Record<string, string> = {
  trend: '趋势', oscillator: '震荡', channel: '通道', volume: '量价'
}

function ScoreBar({ score, label }: { score: number; label: string }) {
  // -100~+100 → 中心归零条形
  const pct = Math.abs(score) / 2
  const positive = score >= 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <span style={{ width: 34, color: 'var(--text-secondary)', fontSize: 12 }}>{label}</span>
      <div style={{ flex: 1, height: 10, background: 'var(--bg-elevated)', borderRadius: 5, position: 'relative' }}>
        <div style={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: 1, background: 'var(--border-color)' }} />
        <div
          style={{
            position: 'absolute', top: 0, bottom: 0, borderRadius: 5,
            left: positive ? '50%' : `${50 - pct}%`,
            width: `${pct}%`,
            background: positive ? '#e0524d' : '#2eab68'
          }}
        />
      </div>
      <span style={{ width: 52, textAlign: 'right', fontSize: 12, color: positive ? '#e0524d' : '#2eab68' }}>
        {score > 0 ? '+' : ''}{score.toFixed(0)}
      </span>
    </div>
  )
}

function signalDir(v: string) {
  if (v === 'up' || v === 'golden_cross' || v === 'bullish' || v === 'bullish_above') return '↑'
  if (v === 'down' || v === 'death_cross' || v === 'bearish' || v === 'bearish_below') return '↓'
  return '→'
}

/** ③ 技术面分析: 四子维度评分条 + 指标信号表 + 权重说明。 */
export default function TechnicalCard({ report }: { report: StockReport }) {
  const tech = report.technical
  return (
    <Card size="small" title="技术面分析" styles={{ body: { padding: '12px 16px' } }}>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 260px', minWidth: 260 }}>
          {(Object.keys(COMP_LABELS) as Array<keyof typeof tech.components>).map((key) => (
            <ScoreBar key={key} label={COMP_LABELS[key]} score={tech.components?.[key]?.score ?? 0} />
          ))}
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            权重: 趋势35% · 震荡25% · 通道15% · 量价25% → 技术总分 {tech.score != null
              ? `${tech.score > 0 ? '+' : ''}${tech.score.toFixed(1)}（${tech.rating}）` : '数据不足'}
          </Typography.Text>
        </div>
        <div style={{ flex: '2 1 420px', minWidth: 340 }}>
          {tech.signals?.length ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: 'var(--text-secondary)', textAlign: 'left' }}>
                  <th style={{ padding: '4px 6px', fontWeight: 500 }}>指标</th>
                  <th style={{ padding: '4px 6px', fontWeight: 500 }}>当前值</th>
                  <th style={{ padding: '4px 6px', fontWeight: 500 }}>信号</th>
                  <th style={{ padding: '4px 6px', fontWeight: 500 }}>方向</th>
                </tr>
              </thead>
              <tbody>
                {tech.signals.map((s, i) => (
                  <tr key={i} style={{ borderTop: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '4px 6px' }}>{s.indicator}</td>
                    <td style={{ padding: '4px 6px', color: 'var(--text-secondary)' }}>
                      {typeof s.value === 'number' ? s.value.toFixed(4) : s.value ?? '—'}
                    </td>
                    <td style={{ padding: '4px 6px' }}>{s.signal}</td>
                    <td style={{ padding: '4px 6px' }}>{signalDir(s.direction)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Typography.Text type="secondary">无信号明细</Typography.Text>
          )}
        </div>
      </div>
    </Card>
  )
}
