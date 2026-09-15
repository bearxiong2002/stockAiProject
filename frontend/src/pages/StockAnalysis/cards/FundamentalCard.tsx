import { Card, Typography } from 'antd'
import type { FundamentalResult, FundItem, StockReport } from '@/types'

function Stat({ name, value, unit }: { name: string; value: number | null; unit?: string }) {
  return (
    <div style={{ background: 'var(--bg-elevated)', borderRadius: 8, padding: '10px 12px', minWidth: 96 }}>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{name}</div>
      <div style={{ fontSize: 17, fontWeight: 700, marginTop: 2 }}>
        {value == null ? '—' : value.toFixed(2)}{unit && <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{unit}</span>}
      </div>
    </div>
  )
}

function itemScoreText(item: FundItem): string {
  return item.score == null ? '缺基准' : item.score > 0 ? `+${item.score}` : String(item.score)
}

/** ④ 基本面分析: 核心指标行 + 三维度分子项评分。 */
export default function FundamentalCard({ report }: { report: StockReport }) {
  const f = report.fundamental
  const it = (dim: 'valuation' | 'growth' | 'health', name: string) =>
    f[dim]?.items?.find((x) => x.name === name)
  const pe = it('valuation', 'PE(TTM)')
  const pb = it('valuation', 'PB')
  const ps = it('valuation', 'PS')
  const roe = it('growth', 'ROE')
  const rev = it('growth', '营收增长率(YoY)')
  const prof = it('growth', '净利润增长率(YoY)')
  const debt = it('health', '资产负债率')
  const ocf = it('health', '经营现金流/净利润')
  const sub = (label: string, s: FundItem[] | undefined, score: number) => (
    <div style={{ flex: '1 1 220px', minWidth: 220 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <Typography.Text strong style={{ fontSize: 12 }}>{label}</Typography.Text>
        <span style={{ color: score > 0 ? '#e0524d' : score < 0 ? '#2eab68' : 'var(--text-secondary)', fontSize: 12 }}>
          {score > 0 ? '+' : ''}{score.toFixed(1)}
        </span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <tbody>
          {s?.map((x, i) => (
            <tr key={i} style={{ borderTop: '1px solid var(--border-color)' }}>
              <td style={{ padding: '3px 4px', color: 'var(--text-secondary)' }}>{x.name}</td>
              <td style={{ padding: '3px 4px' }}>
                {x.value == null ? '—' : typeof x.value === 'number' ? x.value.toFixed(2) : x.value}
                {x.industry_median != null && (
                  <span style={{ color: 'var(--text-secondary)', fontSize: 10 }}> (行业中位 {x.industry_median.toFixed(2)})</span>
                )}
              </td>
              <td style={{ padding: '3px 4px', textAlign: 'right',
                color: (x.score ?? 0) > 0 ? '#e0524d' : (x.score ?? 0) < 0 ? '#2eab68' : 'var(--text-secondary)' }}>
                {itemScoreText(x)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
  return (
    <Card size="small" title="基本面分析" styles={{ body: { padding: '12px 16px' } }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <Stat name="PE(TTM)" value={pe?.value ?? null} />
        <Stat name="PB" value={pb?.value ?? null} />
        <Stat name="PS" value={ps?.value ?? null} />
        <Stat name="ROE" value={roe?.value ?? null} unit="%" />
        <Stat name="营收增长" value={rev?.value ?? null} unit="%" />
        <Stat name="利润增长" value={prof?.value ?? null} unit="%" />
        <Stat name="负债率" value={debt?.value ?? null} unit="%" />
        <Stat name="现金流/净利" value={ocf?.value ?? null} />
      </div>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        {sub(`估值 ${f.valuation.score > 0 ? '+' : ''}${f.valuation.score.toFixed(1)}`, f.valuation?.items, f.valuation.score)}
        {sub(`成长 ${f.growth.score > 0 ? '+' : ''}${f.growth.score.toFixed(1)}`, f.growth?.items, f.growth.score)}
        {sub(`健康 ${f.health.score > 0 ? '+' : ''}${f.health.score.toFixed(1)}`, f.health?.items, f.health.score)}
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 10 }}>
        权重: 估值30% · 成长40% · 健康30% → 基本面总分 {f.score > 0 ? '+' : ''}{f.score.toFixed(1)}（{f.rating}）
        {f.incomplete && ' · 财务数据存在缺口，按可用满分归一'}
      </Typography.Text>
    </Card>
  )
}
