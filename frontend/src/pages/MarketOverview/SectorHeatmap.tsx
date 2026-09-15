import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from '@/components/charts/chartTheme'
import type { SectorItem } from '@/types'

const UP = '#e0524d'
const DOWN = '#2eab68'

function heatColor(pct: number | null, neutral: string): string {
  if (pct == null) return neutral
  const t = Math.max(-3, Math.min(3, pct)) / 3   // ±3% 截断
  if (t >= 0) {
    const k = 0.15 + t * 0.8
    return `rgba(224,82,77,${0.25 + k * 0.75})`
  }
  const t2 = -t
  const k = t2 * 0.9
  return `rgba(46,171,104,${0.25 + k * 0.75})`
}

interface SectorHeatmapProps {
  sectors: SectorItem[]
  height?: number
}

/** 板块热度 TreeMap: 面积=成交额（缺额等分），颜色=涨跌幅红涨绿跌。 */
export default function SectorHeatmap({ sectors, height = 330 }: SectorHeatmapProps) {
  const tokens = useChartTokens()
  const option: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: tokens.tooltipBg, borderColor: tokens.tooltipBorder,
      textStyle: { color: tokens.tooltipText, fontSize: 11 },
      formatter: (p) => {
        const d = (p as unknown as { data: SectorItem & { value?: number } }).data
        return [
          `<strong>${d.name}</strong>`,
          `涨跌幅: <span style="color:${(d.pct_change ?? 0) >= 0 ? UP : DOWN}">${(d.pct_change ?? 0) >= 0 ? '+' : ''}${(d.pct_change ?? 0)?.toFixed?.(2) ?? '—'}%</span>`,
          d.amount_yi != null ? `成交额: ${d.amount_yi} 亿` : '',
          d.leading_stock ? `领涨: ${d.leading_stock} (${d.leading_pct?.toFixed?.(2) ?? '—'}%)` : ''
        ].filter(Boolean).join('<br/>')
      }
    },
    series: [{
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      data: sectors.map((s) => ({
        ...s,
        value: s.amount_yi ?? 1,   // 面积=成交额；缺额保底 1 保证全部可见
        itemStyle: { color: heatColor(s.pct_change, tokens.neutral) },
        label: { show: true, color: '#f0f3f7', fontSize: 10, formatter: '{b}\n{c}'
          , overflow: 'truncate' as const }
      })),
      upperLabel: { show: false },
      itemStyle: { borderColor: tokens.bg, borderWidth: 1, gapWidth: 1 }
    } as echarts.SeriesOption]
  }
  return (
    <div style={{ height }}>
      <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
    </div>
  )
}
