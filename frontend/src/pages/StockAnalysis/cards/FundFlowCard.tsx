import { Card, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import type { StockReport } from '@/types'
import { useEchartsBase } from '@/components/charts/chartTheme'

/** ⑤ 资金面: 近 20 日主力净流入柱状图 + 主力占比折线。 */
export default function FundFlowCard({ report }: { report: StockReport }) {
  const base = useEchartsBase()
  const flow = report.fund_flow
  const chart = flow.chart_data ?? []
  const option: echarts.EChartsOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...base.tooltip },
    legend: { top: 0, textStyle: { color: base.tokens.legendText, fontSize: 10 }, itemWidth: 10, itemHeight: 6 },
    grid: { left: 8, right: 56, top: 22, bottom: 24, containLabel: true },
    xAxis: { type: 'category', data: chart.map((d) => d.date),
      axisLine: base.axisLine,
      axisLabel: base.axisLabel },
    yAxis: [
      { position: 'right', axisLine: { show: false }, axisLabel: base.axisLabel,
        splitLine: base.splitLine },
      { position: 'right', axisLine: { show: false }, axisLabel: { ...base.axisLabel, formatter: (v: number) => `${v}%` },
        splitLine: { show: false } }
    ],
    series: [
      {
        name: '主力净流入(亿)', type: 'bar',
        data: chart.map((d) => ({
          value: d.main_net_inflow,
          itemStyle: { color: d.main_net_inflow >= 0 ? '#e0524d' : '#2eab68' }
        })),
        barWidth: '55%'
      } as echarts.SeriesOption,
      {
        name: '主力占比', type: 'line', yAxisIndex: 1,
        data: chart.map((d) => d.main_net_inflow_pct),
        showSymbol: false, lineStyle: { width: 1, color: '#e6b93c' }
      } as echarts.SeriesOption
    ]
  }
  return (
    <Card size="small" title="资金面" styles={{ body: { padding: '8px 12px' } }}>
      {chart.length === 0 ? (
        <Typography.Text type="secondary">{flow.note ?? '资金流数据不可用'}</Typography.Text>
      ) : (
        <>
          <div style={{ height: 210 }}>
            <ReactECharts option={option} style={{ height: '100%', width: '100%' }} notMerge lazyUpdate />
          </div>
          <div style={{ marginTop: 6, fontSize: 12 }}>
            <span style={{ color: 'var(--text-secondary)' }}>5 日主力净额：</span>
            <span style={{ color: (flow.main_net_inflow_5d ?? 0) >= 0 ? '#e0524d' : '#2eab68', fontWeight: 600 }}>
              {(flow.main_net_inflow_5d ?? 0) >= 0 ? '+' : ''}{(flow.main_net_inflow_5d ?? 0).toFixed(2)} 亿
            </span>
            {flow.main_net_inflow_pct_5d != null && (
              <span style={{ color: 'var(--text-secondary)', marginLeft: 10 }}>
                占成交额 {flow.main_net_inflow_pct_5d >= 0 ? '+' : ''}{flow.main_net_inflow_pct_5d.toFixed(2)}%
              </span>
            )}
            <Typography.Text type="secondary" style={{ marginLeft: 12 }}>
              判断：近期主力净{flow.trend === 'inflow' ? '流入' : '流出'}
            </Typography.Text>
          </div>
        </>
      )}
    </Card>
  )
}
