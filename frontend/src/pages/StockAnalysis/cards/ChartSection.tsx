import { useEffect, useMemo, useState } from 'react'
import { Card, Segmented, Spin } from 'antd'
import KLineChart, { type KLineMark } from '@/components/charts/KLineChart'
import IndicatorChart from '@/components/charts/IndicatorChart'
import api from '@/services/api'
import type { KlineItem, StockReport } from '@/types'

const PERIODS = ['daily', 'weekly', 'monthly'] as const
type Period = (typeof PERIODS)[number]
const PERIOD_LABELS: Record<string, string> = {
  daily: '日线', weekly: '周线', monthly: '月线'
}

/** ② K线与指标: 主图(日/周/月切换) + MACD/KDJ/成交量 三副图，联动缩放。 */
export default function ChartSection({ report }: { report: StockReport }) {
  const [period, setPeriod] = useState('daily')
  const [extra, setExtra] = useState<KlineItem[] | null>(null)
  const [loading, setLoading] = useState(false)

  // 日线直接用报告内置数据；周/月向 /kline 拉取（后端聚合已验证，含缓存）
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

  const kline = useMemo<KlineItem[]>(
    () => (period === 'daily' ? report.kline_data : extra ?? report.kline_data),
    [period, extra, report.kline_data]
  )

  // 信号 → 主图标注（金叉/死叉日期）
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
      }
      styles={{ body: { padding: '10px 12px 4px' } }}
    >
      <div style={{ height: 340, position: 'relative' }}>
        {loading && (
          <div style={{ position: 'absolute', right: 12, top: 8, zIndex: 2 }}>
            <Spin size="small" />
          </div>
        )}
        {/* 周K/月K的 MA 序列未重算：仅在日线叠加均线，避免错位 */}
        <KLineChart
          kline={kline}
          ma={period === 'daily' ? report.indicator_data?.ma : undefined}
          marks={period === 'daily' ? marks : []}
        />
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
