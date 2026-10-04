import { memo, useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useChartTokens } from './chartTheme'
import type { ChipDistribution } from '@/services/api'
import type { KlineItem } from '@/types'

interface ChipChartProps {
  data: ChipDistribution
  kline: KlineItem[]
}

function ChipChart({ data, kline }: ChipChartProps) {
  const t = useChartTokens()

  const option = useMemo<echarts.EChartsOption>(() => {
    const items = data.items
    if (!items.length) return {}

    const lastClose = kline.length ? kline[kline.length - 1].close : null
    const maxPercent = Math.max(...items.map((i) => i.percent))

    const prices = items.map((i) => i.price.toFixed(2))
    const barData = items.map((i) => {
      const isAbove = lastClose != null && i.price >= lastClose
      return {
        value: i.percent,
        itemStyle: {
          color: isAbove ? 'rgba(224,82,77,0.6)' : 'rgba(46,171,104,0.6)',
          borderColor: isAbove ? '#e0524d' : '#2eab68',
          borderWidth: 0.5,
        },
      }
    })

    const markLines: echarts.MarkLineComponentOption['data'] = []
    if (lastClose != null) {
      markLines.push({ yAxis: lastClose.toFixed(2), label: { show: false }, lineStyle: { color: '#f5a623', type: 'dashed', width: 1 } } as any)
    }
    if (data.perf?.weight_avg != null) {
      markLines.push({ yAxis: data.perf.weight_avg.toFixed(2), label: { show: false }, lineStyle: { color: '#4d9de0', type: 'dotted', width: 1 } } as any)
    }

    return {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 10 },
        formatter: (params: any) => {
          const p = Array.isArray(params) ? params[0] : params
          if (!p) return ''
          const winnerRate = data.perf?.winner_rate
          return `价格: ${p.name}<br/>占比: ${Number(p.value).toFixed(2)}%${
            winnerRate != null ? `<br/>获利比: ${winnerRate.toFixed(1)}%` : ''
          }`
        },
      },
      grid: { left: 0, right: 4, top: 24, bottom: 46, containLabel: false },
      xAxis: {
        type: 'value',
        max: maxPercent * 1.1,
        axisLabel: { show: false },
        axisLine: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: prices,
        inverse: false,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: barData,
          barWidth: '80%',
          barCategoryGap: '0%',
          markLine: markLines.length
            ? { symbol: 'none', data: markLines, silent: true }
            : undefined,
        },
      ],
    }
  }, [data, kline, t])

  const winnerRate = data.perf?.winner_rate
  const weightAvg = data.perf?.weight_avg

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: 10, color: t.legendText, padding: '0 4px', lineHeight: '20px', display: 'flex', gap: 8 }}>
        <span>筹码分布</span>
        {winnerRate != null && (
          <span style={{ color: winnerRate > 50 ? '#e0524d' : '#2eab68' }}>
            获利 {winnerRate.toFixed(1)}%
          </span>
        )}
      </div>
      <div style={{ flex: 1 }}>
        <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
      </div>
      {weightAvg != null && (
        <div style={{ fontSize: 9, color: t.legendText, padding: '0 4px', textAlign: 'center' }}>
          均价 {weightAvg.toFixed(2)}
        </div>
      )}
    </div>
  )
}

export default memo(ChipChart)
