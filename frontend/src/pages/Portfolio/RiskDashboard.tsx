import { Card, Col, Empty, Row, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import RiskMatrix from './RiskMatrix'
import type { PortfolioRisk } from '@/types'
import { useEchartsBase } from '@/components/charts/chartTheme'

const UP = '#e0524d'
const DOWN = '#2eab68'

function RiskCard({ name, value, sub, color }: {
  name: string; value: string; sub?: string; color?: string
}) {
  return (
    <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{name}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color ?? 'var(--text-primary)', marginTop: 2 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>{sub}</div>}
    </Card>
  )
}

const pct = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : `${v.toFixed(digits)}%`

const ratio = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : v.toFixed(digits)

function riskColor(text: string | null | undefined): string {
  if (!text) return 'var(--text-secondary)'
  if (text.includes('高')) return DOWN
  if (text.includes('中')) return '#e6a23c'
  return UP
}

/** 下半部分: 风险概览卡片行 + 行业饼图 + 相关性热力图 + 净值曲线。 */
export default function RiskDashboard({ risk }: { risk: PortfolioRisk | null }) {
  const base = useEchartsBase()
  if (!risk) {
    return <Card size="small"><Empty description="风险数据加载中" /></Card>
  }
  if (risk.incomplete) {
    return (
      <Card size="small" title="风险评估">
        <Empty description={risk.note ?? '数据不足'} />
        {risk.detail && (
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {risk.detail}
          </Typography.Text>
        )}
      </Card>
    )
  }
  const dd = risk.max_drawdown!
  const sector = risk.sector_exposure!
  const corr = risk.correlation!
  const curve = risk.portfolio_curve!
  const pieOption: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', ...base.tooltip },
    legend: { bottom: 0, textStyle: { color: base.tokens.legendText, fontSize: 10 }, itemWidth: 10 },
    series: [{
      type: 'pie', radius: ['40%', '68%'], center: ['50%', '44%'],
      data: sector.sectors.map((s, i) => ({
        name: s.industry, value: Math.round(s.weight_pct * 100) / 100,
        itemStyle: {
          color: ['#e0524d', '#e6b93c', '#4d9de0', '#2eab68', '#c86be0',
                  base.tokens.neutral, '#e6a23c', '#1a6b41'][i % 8]
        }
      })),
      label: { color: base.tokens.axisLabel, fontSize: 10, formatter: '{b} {d}%' }
    }]
  }
  const curveOption: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...base.tooltip },
    legend: { top: 0, textStyle: { color: base.tokens.legendText, fontSize: 10 }, itemWidth: 12 },
    grid: { left: 8, right: 14, top: 24, bottom: 24, containLabel: true },
    xAxis: { type: 'category', data: curve.dates,
      axisLabel: base.axisLabel },
    yAxis: { scale: true, axisLabel: base.axisLabel,
      splitLine: base.splitLine },
    series: [
      { name: '组合净值', type: 'line', data: curve.portfolio, showSymbol: false,
        lineStyle: { width: 1.5, color: UP } },
      { name: '沪深300', type: 'line', data: curve.benchmark, showSymbol: false,
        lineStyle: { width: 1.2, color: '#4d9de0' } }
    ]
  }
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '18px 0 10px' }}>
        <Typography.Text strong style={{ fontSize: 14 }}>风险评估</Typography.Text>
        <span style={{
          color: '#0f1115', background: riskColor(risk.risk_level),
          borderRadius: 4, padding: '2px 10px', fontSize: 12, fontWeight: 600
        }}>
          {risk.risk_level}
        </span>
      </div>
      <Row gutter={[10, 10]}>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name="VaR 95%（单日）"
            value={`${ratio(risk.var?.['95']?.pct)}%`}
            sub={`≈ ${risk.var?.['95']?.amount?.toLocaleString() ?? '—'} 元`} color={DOWN} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name="最大回撤" value={`${ratio(dd.max)}%`}
            sub={`${dd.start?.slice(5, 10) ?? ''} → ${dd.end?.slice(5, 10) ?? ''} · 当前 ${ratio(dd.current)}%`} color={DOWN} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name="年化波动率"
            value={`${ratio(risk.volatility?.portfolio)}%`}
            sub={`沪深300 ${ratio(risk.volatility?.index)}%`} color="#e6a23c" />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name="Beta（vs 沪深300）" value={ratio(risk.beta)}
            sub={risk.beta == null ? '' : risk.beta > 1.2 ? '高风险' : risk.beta < 0.8 ? '防御型' : '中等'}
            color={(risk.beta ?? 0) > 1.2 ? DOWN : undefined} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name="夏普比率" value={ratio(risk.sharpe)}
            sub="年化收益−无风险利率 / 波动率"
            color={(risk.sharpe ?? 0) >= 0 ? UP : DOWN} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <RiskCard name={`集中度（${risk.concentration?.level}）`}
            value={`${risk.concentration?.top3_pct ?? '—'}%`}
            sub={`HHI ${risk.concentration?.hhi ?? '—'} · 前 3 大持仓占比`}
            color={riskColor(risk.concentration?.level)} />
        </Col>
      </Row>
      <Row gutter={[10, 10]} style={{ marginTop: 10 }}>
        <Col xs={24} xl={8}>
          <Card size="small" title="行业分布" styles={{ body: { padding: '8px 10px' } }}>
            <div style={{ height: 250 }}>
              <ReactECharts option={pieOption} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="相关性矩阵" styles={{ body: { padding: '8px 10px' } }}>
            {corr && corr.codes.length >= 2 ? (
              <>
                <RiskMatrix codes={corr.codes} matrix={corr.matrix} height={230} />
                {corr.high_pairs.length > 0 && (
                  <Typography.Text type="warning" style={{ fontSize: 11 }}>
                    高相关: {corr.high_pairs.map((h) => `${h.pair[0]}↔${h.pair[1]} ${h.corr}`).join('；')}
                  </Typography.Text>
                )}
              </>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="持仓不足 2 只，隐藏相关性分析" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="组合净值 vs 沪深300" styles={{ body: { padding: '8px 10px' } }}>
            <div style={{ height: 250 }}>
              <ReactECharts option={curveOption} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
            </div>
          </Card>
        </Col>
      </Row>
      {risk.warnings && risk.warnings.length > 0 && (
        <Card size="small" title="风险提示" styles={{ body: { padding: '10px 14px', marginTop: 10 } }}>
          {risk.warnings.map((w, i) => (
            <div key={i} style={{ fontSize: 12, color: '#e6a23c', padding: '3px 0' }}>⚠ {w}</div>
          ))}
        </Card>
      )}
    </>
  )
}
