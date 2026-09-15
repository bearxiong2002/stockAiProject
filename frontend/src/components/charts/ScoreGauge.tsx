import { memo } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from './chartTheme'

/** 评分 → 颜色（A 股语义: 正=红看多，负=绿看空；两端加深） */
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#8b93a1'
  if (score >= 60) return '#8c1f1b'      // 深红
  if (score >= 20) return '#e0524d'      // 红
  if (score > -20) return '#8b93a1'      // 灰
  if (score > -60) return '#2eab68'      // 绿
  return '#1a6b41'                        // 深绿
}

interface ScoreGaugeProps {
  score: number | null
  label: string
  width?: number
  small?: boolean
}

function ScoreGauge({ score, label, width = 160, small = false }: ScoreGaugeProps) {
  const tokens = useChartTokens()
  const value = score == null ? 0 : Math.max(-100, Math.min(100, score))
  const height = Math.round(width * 0.72)
  const option: echarts.EChartsOption = {
    series: [
      {
        type: 'gauge',
        startAngle: 180,
        endAngle: 0,
        min: -100,
        max: 100,
        radius: '100%',
        center: ['50%', '78%'],
        splitNumber: 5,
        itemStyle: { color: scoreColor(score) },
        progress: {
          show: score != null,
          width: small ? 8 : 12,
          roundCap: true,
          itemStyle: { color: scoreColor(score) }
        },
        pointer: { show: false },
        axisLine: { lineStyle: { width: small ? 8 : 12, color: [[1, tokens.neutral]] } },
        axisTick: { show: false },
        splitLine: { show: true, length: small ? 2 : 4, distance: -(small ? 8 : 12) - 2,
          lineStyle: { color: tokens.axisLine, width: 1 } },
        axisLabel: { show: !small, distance: -(small ? 8 : 12) - 14,
          color: tokens.axisLabel, fontSize: 9,
          formatter: (v: number) => (v === 100 || v === -100 || v === 0 ? String(v) : '') },
        anchor: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, small ? '-8%' : '-12%'],
          formatter: score == null ? ' ' : `${score > 0 ? '+' : ''}${score.toFixed(1)}`,
          color: scoreColor(score),
          fontSize: small ? 15 : 22,
          fontWeight: 700
        },
        data: [{ value: score ?? 0 }]
      }
    ],
    graphic: [
      {
        type: 'text' as const, left: 'center', top: small ? 18 : 24,
        style: { text: label, fill: tokens.textPrimary, fontSize: small ? 11 : 13,
                 fontWeight: 600 }
      },
      ...(score == null
        ? [{ type: 'text' as const, left: 'center', top: '52%',
             style: { text: '数据不足', fill: tokens.axisLabel, fontSize: 10 } }]
        : [])
    ]
  }
  return (
    <div style={{ width, height }}>
      <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
    </div>
  )
}

export default memo(ScoreGauge)
