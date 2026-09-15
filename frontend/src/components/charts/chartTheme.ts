import { useThemeStore } from '@/stores/theme'

/** ECharts 颜色 token（亮/暗主题切换时图表同步换色）。 */
export interface ChartTokens {
  axisLabel: string
  axisLine: string
  splitLine: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  crosshair: string
  zoomBg: string
  zoomBorder: string
  zoomHandle: string
  zoomText: string
  legendText: string
  legendBorder: string
  neutral: string
  /** 页面底色（treemap/heatmap 分隔线用） */
  bg: string
  /** 正文色（热力图数值标签用） */
  textPrimary: string
}

const DARK: ChartTokens = {
  axisLabel: '#8b93a1',
  axisLine: '#2a2f38',
  splitLine: '#22262e',
  tooltipBg: '#1d222a',
  tooltipBorder: '#2a2f38',
  tooltipText: '#d8dde6',
  crosshair: '#5a6270',
  zoomBg: '#161a20',
  zoomBorder: '#2a2f38',
  zoomHandle: '#3a4150',
  zoomText: '#8b93a1',
  legendText: '#8b93a1',
  legendBorder: '#2a2f38',
  neutral: '#3a4150',
  bg: '#0f1115',
  textPrimary: '#d8dde6'
}

const LIGHT: ChartTokens = {
  axisLabel: '#6b7280',
  axisLine: '#d8dce3',
  splitLine: '#eceef2',
  tooltipBg: '#ffffff',
  tooltipBorder: '#e2e5ea',
  tooltipText: '#1f2430',
  crosshair: '#9aa2b1',
  zoomBg: '#ffffff',
  zoomBorder: '#e2e5ea',
  zoomHandle: '#c3c8d0',
  zoomText: '#6b7280',
  legendText: '#6b7280',
  legendBorder: '#e2e5ea',
  neutral: '#c3c8d0',
  bg: '#f5f6f8',
  textPrimary: '#1f2430'
}

export function useChartTokens(): ChartTokens {
  const mode = useThemeStore((s) => s.mode)
  return mode === 'dark' ? DARK : LIGHT
}

/** 常用 ECharts option 片段（页面内联图表用，随主题切换）。 */
export function useEchartsBase() {
  const tokens = useChartTokens()
  return {
    tokens,
    tooltip: {
      backgroundColor: tokens.tooltipBg,
      borderColor: tokens.tooltipBorder,
      textStyle: { color: tokens.tooltipText, fontSize: 11 }
    },
    axisLabel: { color: tokens.axisLabel, fontSize: 9 },
    axisLine: { lineStyle: { color: tokens.axisLine } },
    splitLine: { lineStyle: { color: tokens.splitLine } },
    neutral: tokens.neutral
  }
}

export { DARK as DARK_CHART_TOKENS, LIGHT as LIGHT_CHART_TOKENS }
