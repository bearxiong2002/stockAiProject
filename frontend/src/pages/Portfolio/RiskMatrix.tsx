import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from '@/components/charts/chartTheme'

interface RiskMatrixProps {
  codes: string[]
  matrix: (number | null)[][]
  height?: number
}

/** 相关性热力图（ECharts heatmap，-1~1 绿→灰→红渐变）。 */
export default function RiskMatrix({ codes, matrix, height = 260 }: RiskMatrixProps) {
  const tokens = useChartTokens()
  const data: [number, number, number][] = []
  for (let i = 0; i < matrix.length; i++) {
    for (let j = 0; j < matrix[i].length; j++) {
      const v = matrix[i][j]
      if (v != null) data.push([j, i, Math.round(v * 100) / 100])
    }
  }
  const option: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: { backgroundColor: tokens.tooltipBg, borderColor: tokens.tooltipBorder,
      textStyle: { color: tokens.tooltipText, fontSize: 11 } },
    grid: { left: 8, right: 60, top: 4, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: codes, axisLine: { lineStyle: { color: tokens.axisLine } },
      axisLabel: { color: tokens.axisLabel, fontSize: 9 } },
    yAxis: { type: 'category', data: codes, axisLine: { lineStyle: { color: tokens.axisLine } },
      axisLabel: { color: tokens.axisLabel, fontSize: 9 } },
    visualMap: {
      min: -1, max: 1, calculable: true,
      orient: 'vertical', right: 0, top: 'center',
      inRange: { color: ['#2eab68', tokens.neutral, '#e0524d'] },
      textStyle: { color: tokens.axisLabel, fontSize: 9 }
    },
    series: [{
      type: 'heatmap', data,
      label: { show: true, color: tokens.textPrimary, fontSize: 9,
        formatter: (p) => {
          const v = (p as unknown as { value: [number, number, number] }).value
          return String(v?.[2])
        } },
      itemStyle: { borderColor: tokens.bg, borderWidth: 1 }
    }] as echarts.SeriesOption[]
  }
  return (
    <div style={{ height }}>
      <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
    </div>
  )
}
