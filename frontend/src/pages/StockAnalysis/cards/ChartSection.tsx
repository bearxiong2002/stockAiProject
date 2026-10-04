import { useEffect, useMemo, useState } from 'react'
import { Card, Segmented, Spin, Switch } from 'antd'
import KLineChart, { type KLineMark } from '@/components/charts/KLineChart'
import IndicatorChart from '@/components/charts/IndicatorChart'
import ChipChart from '@/components/charts/ChipChart'
import api, { getChipDistribution, type ChipDistribution } from '@/services/api'
import type { KlineItem, StockReport } from '@/types'

const PERIODS = ['daily', 'weekly', 'monthly'] as const
type Period = (typeof PERIODS)[number]

/** ② K线与指标: 主图(日/周/月切换) + MACD/KDJ/成交量 三副图，联动缩放。 */
export default function ChartSection({ report }: { report: StockReport }) {
  const [period, setPeriod] = useState('daily')
  const [extra, setExtra] = useState<KlineItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [showChips, setShowChips] = useState(false)
  const [chipData, setChipData] = useState<ChipDistribution | null>(null)
  const [chipLoading, setChipLoading] = useState(false)

  useEffect(() => {
    if (period === 'daily') {
      setExtra(null)
      return
    }
    let alive = true
    setLoading(true)
    api
      .get(`/stock/${report.stock_info.code}/kline`, { params: { period, days: 250 } })
      .then(({ data }) => {
        if (alive) setExtra(data.items as KlineItem[])
      })
      .catch(() => {
        if (alive) setExtra(null)
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [period, report.stock_info.code])

  useEffect(() => {
    if (!showChips) return
    if (chipData) return
    let alive = true
    setChipLoading(true)
    getChipDistribution(report.stock_info.code)
      .then((d) => {
        if (alive) setChipData(d)
      })
      .catch(() => {})
      .finally(() => alive && setChipLoading(false))
    return () => { alive = false }
  }, [showChips, chipData, report.stock_info.code])

  const kline = useMemo<KlineItem[]>(
    () => (period === 'daily' ? report.kline_data : extra ?? report.kline_data),
    [period, extra, report.kline_data]
  )

  const marks = useMemo<KLineMark[]>(() => {
    const sig = report.technical?.signals ?? []
    return sig
      .filter((s) => s.signal === 'golden_cross' || s.signal === 'death_cross')
      .filter((s) => s.crossed_at != null)
      .map((s) => ({
        date: String(s.crossed_at),
        type: s.signal as KLineMark['type'],
        label: s.indicator
      }))
  }, [report])

  return (
    <Card
      size="small"
      title="K线与指标"
      extra={
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            筹码
            <Switch
              size="small"
              checked={showChips}
              onChange={setShowChips}
              loading={chipLoading}
            />
          </span>
          <Segmented
            size="small"
            value={period}
            onChange={(v) => setPeriod(v as string)}
            options={[
              { value: 'daily', label: '日线' },
              { value: 'weekly', label: '周线' },
              { value: 'monthly', label: '月线' }
            ]}
          />
        </div>
      }
      styles={{ body: { padding: '10px 12px 4px' } }}
    >
      <div style={{ display: 'flex', height: 340, position: 'relative' }}>
        {loading && (
          <div style={{ position: 'absolute', right: 12, top: 8, zIndex: 2 }}>
            <Spin size="small" />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <KLineChart
            kline={kline}
            ma={period === 'daily' ? report.indicator_data?.ma : undefined}
            marks={period === 'daily' ? marks : []}
          />
        </div>
        {showChips && chipData && chipData.items.length > 0 && (
          <div style={{ width: 160, flexShrink: 0 }}>
            <ChipChart data={chipData} kline={kline} />
          </div>
        )}
      </div>
      {period === 'daily' ? (
        <>
          <div style={{ height: 150, marginTop: 6 }}>
            <IndicatorChart
              type="macd"
              series={report.indicator_data}
              closes={report.kline_data.map((k) => k.close)}
            />
          </div>
          <div style={{ height: 170, marginTop: 6 }}>
            <IndicatorChart type="kdj" series={report.indicator_data} />
          </div>
          <div style={{ height: 170, marginTop: 6 }}>
            <IndicatorChart
              type="volume"
              series={report.indicator_data}
              closes={report.kline_data.map((k) => k.close)}
            />
          </div>
        </>
      ) : (
        <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>
          技术指标副图仅在日线模式下显示
        </div>
      )}
    </Card>
  )
}
