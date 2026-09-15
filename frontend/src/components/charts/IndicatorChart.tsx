import { memo } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { CHART_GROUP } from './KLineChart'
import { useChartTokens } from './chartTheme'
import type { IndicatorSeries } from '@/types'

export type IndicatorType = 'macd' | 'kdj' | 'volume'

interface IndicatorChartProps {
  type: IndicatorType
  series: IndicatorSeries
  /** 成交量柱按当日涨跌着色需要收盘价序列（type=volume 时建议传入） */
  closes?: (number | null)[]
  height?: number
}

/** 技术指标副图: MACD（DIF/DEA+柱） / KDJ（三线+超买超卖区） / 成交量（涨红跌绿+均量线）。 */
function IndicatorChart({ type, series, closes, height }: IndicatorChartProps) {
  const tokens = useChartTokens()
  const dates = series.dates
  const BASE_TEXT = { color: tokens.axisLabel, fontSize: 10 }
  const TOOLTIP = {
    trigger: 'axis' as const,
    axisPointer: { type: 'line' as const },
    backgroundColor: tokens.tooltipBg,
    borderColor: tokens.tooltipBorder,
    textStyle: { color: tokens.tooltipText, fontSize: 11 }
  }
  let option: echarts.EChartsOption

  if (type === 'macd') {
    const hist = series.macd.macd_hist
    option = {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: TOOLTIP,
      legend: { top: 0, textStyle: BASE_TEXT, itemWidth: 10, itemHeight: 7,
        data: ['DIF', 'DEA', 'MACD'] },
      grid: { left: 8, right: 56, top: 22, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: tokens.axisLine } },
        axisLabel: { ...BASE_TEXT, show: false }, splitLine: { show: false } },
      yAxis: { position: 'right', axisLine: { show: false }, axisLabel: BASE_TEXT,
        splitLine: { lineStyle: { color: tokens.splitLine } } },
      series: [
        {
          name: 'MACD', type: 'bar', data: hist, barWidth: 1,
          itemStyle: {
            color: (p) => ((p.value as number) >= 0 ? '#e0524d' : '#2eab68')
          }
        },
        { name: 'DIF', type: 'line', data: series.macd.dif, showSymbol: false,
          lineStyle: { width: 1, color: '#e6b93c' } },
        { name: 'DEA', type: 'line', data: series.macd.dea, showSymbol: false,
          lineStyle: { width: 1, color: '#4d9de0' } }
      ] as echarts.SeriesOption[]
    }
  } else if (type === 'kdj') {
    option = {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: TOOLTIP,
      legend: { top: 0, textStyle: BASE_TEXT, itemWidth: 10, itemHeight: 6,
        data: ['K', 'D', 'J'] },
      grid: { left: 8, right: 56, top: 22, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: tokens.axisLine } },
        axisLabel: { ...BASE_TEXT, show: false }, splitLine: { show: false } },
      yAxis: { position: 'right', min: -20, max: 120, axisLine: { show: false },
        axisLabel: BASE_TEXT, splitLine: { lineStyle: { color: tokens.splitLine } } },
      series: [
        { name: 'K', type: 'line', data: series.kdj.kdj_k, showSymbol: false,
          lineStyle: { width: 1, color: '#e6b93c' } },
        { name: 'D', type: 'line', data: series.kdj.kdj_d, showSymbol: false,
          lineStyle: { width: 1, color: '#4d9de0' } },
        { name: 'J', type: 'line', data: series.kdj.kdj_j, showSymbol: false,
          lineStyle: { width: 1, color: '#c86be0', type: 'dashed' } },
        {
          name: '超买区', type: 'line', data: [], markArea: {
            silent: true, itemStyle: { color: 'rgba(224,82,77,0.07)' },
            data: [[{ yAxis: 80 }, { yAxis: 120 }]] }
        } as echarts.SeriesOption,
        {
          name: '超卖区', type: 'line', data: [], markArea: {
            silent: true, itemStyle: { color: 'rgba(46,171,104,0.07)' },
            data: [[{ yAxis: -20 }, { yAxis: 20 }]] }
        } as echarts.SeriesOption
      ] as echarts.SeriesOption[]
    }
  } else {
    const vol = series.volume.volume
    const colors = closes
      ? closes.map((c, i) => {
          const prev = closes[i - 1]
          if (c == null || prev == null) return tokens.neutral
          return c >= prev ? '#e0524d' : '#2eab68'
        })
      : '#4d9de0'
    option = {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: TOOLTIP,
      legend: { top: 0, textStyle: BASE_TEXT, itemWidth: 10, itemHeight: 6,
        data: ['成交量', 'MA5', 'MA10'] },
      grid: { left: 8, right: 56, top: 22, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: tokens.axisLine } },
        axisLabel: { ...BASE_TEXT, show: false }, splitLine: { show: false } },
      yAxis: { position: 'right', axisLine: { show: false }, axisLabel: BASE_TEXT,
        splitLine: { lineStyle: { color: tokens.splitLine } } },
      series: [
        {
          name: '成交量', type: 'bar', data: vol.map((v, i) => ({
            value: v, itemStyle: { color: Array.isArray(colors) ? colors[i] : colors }
          })),
          barWidth: '60%'
        } as echarts.SeriesOption,
        { name: 'MA5', type: 'line', data: series.volume.vol_ma_5, showSymbol: false,
          lineStyle: { width: 1, color: '#e6b93c' } },
        { name: 'MA10', type: 'line', data: series.volume.vol_ma_10, showSymbol: false,
          lineStyle: { width: 1, color: '#c86be0' } }
      ] as echarts.SeriesOption[]
    }
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: height ?? '100%', width: '100%' }}
      notMerge
      lazyUpdate
      onChartReady={(inst) => {
        inst.group = CHART_GROUP
        echarts.connect(CHART_GROUP)
      }}
    />
  )
}

export default memo(IndicatorChart)
