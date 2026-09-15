import { memo, useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from './chartTheme'
import type { KlineItem } from '@/types'

export const CHART_GROUP = 'stockpanel-analysis'

/** 图表联动: 同组实例缩放/时间轴同步（K线主图与各副图共用）。 */
export function connectCharts(instances: (echarts.ECharts | undefined | null)[]) {
  const live = instances.filter(Boolean) as echarts.ECharts[]
  for (const c of live) c.group = CHART_GROUP
  if (live.length) echarts.connect(CHART_GROUP)
}

const MA_COLORS: Record<string, string> = {
  ma_5: '#e6b93c',
  ma_10: '#4d9de0',
  ma_20: '#c86be0',
  ma_60: '#2eab68'
}
const MA_LABELS: Record<string, string> = {
  ma_5: 'MA5', ma_10: 'MA10', ma_20: 'MA20', ma_60: 'MA60'
}

export interface KLineMark {
  date: string
  type: 'golden_cross' | 'death_cross'
  label: string
}

interface KLineChartProps {
  kline: KlineItem[]
  /** 叠加均线 {ma_5: [...]}（与 kline 等长，缺测为 null） */
  ma?: Record<string, (number | null)[]>
  /** 信号标注（金叉/死叉） */
  marks?: KLineMark[]
}

/** 日K 主图: 蜡烛图 + MA 叠加 + dataZoom（inside+slider）+ 十字光标 + 信号标注。 */
function KLineChart({ kline, ma, marks = [] }: KLineChartProps) {
  const t = useChartTokens()
  const option = useMemo<echarts.EChartsOption>(() => {
    const dates = kline.map((k) => k.date)
    const candles = kline.map((k) => [k.open, k.close, k.low, k.high])
    const maSeries: echarts.SeriesOption[] = ma
      ? Object.keys(MA_COLORS)
          .filter((key) => ma[key])
          .map((key) => ({
            name: MA_LABELS[key],
            type: 'line' as const,
            data: ma[key],
            showSymbol: false,
            lineStyle: { width: 1, color: MA_COLORS[key] }
          }))
      : []
    const markPoints = marks.flatMap((m) => {
      const idx = dates.indexOf(m.date)
      if (idx < 0) return []
      const close = kline[idx].close
      if (close == null) return []
      return [{
        coord: [m.date, close],
        symbol: m.type === 'golden_cross' ? 'triangle' : 'arrow',
        symbolSize: 10,
        symbolRotate: m.type === 'golden_cross' ? 0 : 180,
        itemStyle: { color: m.type === 'golden_cross' ? '#e0524d' : '#2eab68' }
      }]
    })
    return {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: t.crosshair } },
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 }
      },
      legend: {
        top: 0,
        textStyle: { color: t.legendText, fontSize: 10 },
        itemWidth: 12,
        itemHeight: 8
      },
      grid: { left: 8, right: 56, top: 24, bottom: 46, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: t.axisLine } },
        axisLabel: { color: t.axisLabel, fontSize: 10 },
        splitLine: { show: false }
      },
      yAxis: {
        scale: true,
        position: 'right',
        axisLine: { show: false },
        axisLabel: { color: t.axisLabel, fontSize: 10 },
        splitLine: { lineStyle: { color: t.splitLine } }
      },
      dataZoom: [
        { type: 'inside', start: 60, end: 100 },
        { type: 'slider', start: 60, end: 100, height: 18, bottom: 6,
          borderColor: t.zoomBorder, backgroundColor: t.zoomBg,
          fillerColor: 'rgba(224,82,77,0.15)', handleStyle: { color: t.zoomHandle },
          textStyle: { color: t.zoomText, fontSize: 9 } }
      ],
      series: [
        {
          name: '日K',
          type: 'candlestick',
          data: candles,
          itemStyle: {
            color: '#e0524d',        // 阳线(涨) 红
            color0: '#2eab68',       // 阴线(跌)
            borderColor: '#e0524d',
            borderColor0: '#2eab68'
          },
          markPoint: markPoints.length ? { data: markPoints } : undefined
        },
        ...maSeries
      ] as echarts.SeriesOption[]
    }
  }, [kline, ma, marks, t])

  return (
    <ReactECharts
      option={option}
      style={{ height: '100%', width: '100%' }}
      notMerge
      lazyUpdate
      onChartReady={(inst) => {
        inst.group = CHART_GROUP
        echarts.connect(CHART_GROUP)
      }}
    />
  )
}

export default memo(KLineChart)
