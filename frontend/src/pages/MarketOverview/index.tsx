import { useCallback, useEffect, useState } from 'react'
import { Alert, Card, Col, Row, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import SectorHeatmap from './SectorHeatmap'
import { PageError, PageLoading } from '@/components/PageState'
import { useNavigate } from 'react-router-dom'
import {
  getMarketFundFlow, getMarketIndices, getMarketSectors, getMarketStatistics
} from '@/services/api'
import type { MarketFundFlowItem, MarketIndexItem, MarketStatistics, SectorItem } from '@/types'
import { useEchartsBase } from '@/components/charts/chartTheme'

const UP = '#e0524d'
const DOWN = '#2eab68'

/** 大盘概览（design 4.9）: 指数卡片行 + 板块热力图 + 资金流向 + 涨跌统计。 */
export default function MarketOverview() {
  const [indices, setIndices] = useState<MarketIndexItem[]>([])
  const [sectors, setSectors] = useState<SectorItem[]>([])
  const [flow, setFlow] = useState<MarketFundFlowItem[]>([])
  const [stats, setStats] = useState<MarketStatistics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setError(null)
    try {
      const [i, s, f, st] = await Promise.all([
        getMarketIndices(), getMarketSectors(), getMarketFundFlow(10), getMarketStatistics()
      ])
      setIndices(i.items)
      setSectors(s.items)
      setFlow(f.items)
      setStats(st)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    load().finally(() => setLoading(false))
  }, [load])

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Typography.Text strong style={{ fontSize: 15 }}>大盘概览</Typography.Text>
        {stats?.as_of && <Typography.Text type="secondary" style={{ fontSize: 11 }}>截至 {stats.as_of}</Typography.Text>}
      </div>
      {error && (
        <Alert type="error" showIcon style={{ marginBottom: 10 }} message={`加载失败: ${error}`} />
      )}
      {loading && indices.length === 0 && !error ? (
        <PageLoading tip="正在加载大盘数据..." />
      ) : error && indices.length === 0 ? (
        <PageError title="大盘数据加载失败" message={error} onRetry={load} />
      ) : (
        <>
          {/* ① 指数卡片行 */}
          <Row gutter={[10, 10]}>
            {indices.map((it) => (
              <Col xs={12} md={6} key={it.code}>
                <Card size="small" hoverable onClick={() => navigate(`/analysis`)}
                  styles={{ body: { padding: '10px 14px' } }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{it.name}</div>
                  <div style={{ fontSize: 20, fontWeight: 700, marginTop: 2 }}>
                    {it.close?.toLocaleString() ?? '—'}
                  </div>
                  {it.pct_change != null && (
                    <div style={{ color: it.pct_change >= 0 ? UP : DOWN, fontSize: 13 }}>
                      {it.pct_change >= 0 ? '+' : ''}{it.pct_change?.toFixed(2)}%
                    </div>
                  )}
                  <div style={{ color: 'var(--text-secondary)', fontSize: 10, marginTop: 2 }}>
                    成交 {it.amount_yi != null ? `${it.amount_yi.toLocaleString()} 亿` : '—'}
                  </div>
                  {it.sparkline && it.sparkline.length > 1 && (
                    <div style={{ height: 56, marginTop: 6 }}>
                      <ReactECharts
                        option={{
                          animation: false, backgroundColor: 'transparent',
                          grid: { left: 0, right: 0, top: 4, bottom: 0 },
                          xAxis: { type: 'category', show: false, data: it.sparkline.map((_, i) => i) },
                          yAxis: { type: 'value', show: false, scale: true },
                          series: [{
                            type: 'line', data: it.sparkline, symbol: 'none',
                            lineStyle: { width: 1.2, color: (it.pct_change ?? 0) >= 0 ? UP : DOWN },
                            areaStyle: {
                              color: (it.pct_change ?? 0) >= 0
                                ? 'rgba(224,82,77,0.12)' : 'rgba(46,171,104,0.12)'
                            }
                          }]
                        } as echarts.EChartsOption}
                        style={{ height: '100%', width: '100%' }} notMerge lazyUpdate
                      />
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={[10, 10]} style={{ marginTop: 10 }}>
            {/* ② 板块热力图 */}
            <Col xs={24} xl={14}>
              <Card size="small" title="板块热度（申万一级 · 面积=成交额）"
                styles={{ body: { padding: '6px 10px' } }}>
                <SectorHeatmap sectors={sectors} />
              </Card>
            </Col>
            <Col xs={24} xl={10}>
              {/* ④ 涨跌统计 */}
              <Card size="small" title="涨跌统计" styles={{ body: { padding: '10px 14px' } }}>
                {stats == null || (stats.up == null && stats.down == null) ? (
                  <Typography.Text type="secondary">{stats?.note ?? '暂无数据'}</Typography.Text>
                ) : (
                  <>
                    <div style={{ display: 'flex', height: 26, borderRadius: 5, overflow: 'hidden', margin: '8px 0 12px' }}>
                      {stats.up != null && (
                        <div style={{ width: `${(stats.up / Math.max(1, (stats.up ?? 0) + (stats.down ?? 0) + (stats.flat ?? 0))) * 100}%`,
                          background: UP, display: 'grid', placeItems: 'center', color: '#fff', fontSize: 11 }}>
                          涨 {stats.up}
                        </div>
                      )}
                      {stats.down != null && (
                        <div style={{ width: `${((stats.down ?? 0) / Math.max(1, (stats.up ?? 0) + (stats.down ?? 0) + (stats.flat ?? 0))) * 100}%`,
                          background: DOWN, display: 'grid', placeItems: 'center', color: '#fff', fontSize: 12 }}>
                          跌 {stats.down}
                        </div>
                      )}
                      {(stats.flat ?? 0) > 0 && (
                        <div style={{ width: `${((stats.flat ?? 0) / Math.max(1, (stats.up ?? 0) + (stats.down ?? 0) + (stats.flat ?? 0))) * 100}%`,
                          background: '#3a4150', display: 'grid', placeItems: 'center', color: '#d8dde6', fontSize: 11 }}>
                          {stats.flat}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>涨停</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: stats.limit_up != null ? UP : 'var(--text-secondary)' }}>
                          {stats.limit_up ?? '—'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>跌停</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: stats.limit_down != null ? DOWN : 'var(--text-secondary)' }}>
                          {stats.limit_down ?? '—'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>样本</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{stats.total ?? '—'}</div>
                      </div>
                    </div>
                  </>
                )}
              </Card>
              {/* ③ 资金流向 */}
              <Card size="small" title="大盘资金流向（近 10 日）"
                style={{ marginTop: 10 }} styles={{ body: { padding: '6px 10px' } }}>
                <FundFlowChart items={flow} />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  )
}

function FundFlowChart({ items }: { items: MarketFundFlowItem[] }) {
  const base = useEchartsBase()
  if (!items.length) {
    return <Typography.Text type="secondary" style={{ fontSize: 12 }}>大盘资金流数据暂不可用</Typography.Text>
  }
  const option: echarts.EChartsOption = {
    animation: false, backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...base.tooltip },
    grid: { left: 8, right: 10, top: 10, bottom: 22, containLabel: true },
    xAxis: { type: 'category', data: items.map((d) => d.date.slice(5, 10)),
      axisLabel: base.axisLabel },
    yAxis: { axisLabel: base.axisLabel, splitLine: base.splitLine },
    series: [{
      name: '主力净流入(亿)', type: 'bar',
      data: items.map((d) => ({
        value: d.main_net_inflow,
        itemStyle: { color: d.main_net_inflow >= 0 ? UP : DOWN }
      })),
      barWidth: '55%'
    }]
  }
  return (
    <div style={{ height: 200 }}>
      <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
    </div>
  )
}
