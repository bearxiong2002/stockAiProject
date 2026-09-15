import { useCallback, useEffect, useState } from 'react'
import { Alert, Empty } from 'antd'
import HoldingTable from './HoldingTable'
import RiskDashboard from './RiskDashboard'
import AiAdviceCard from './AiAdviceCard'
import { PageError, PageLoading } from '@/components/PageState'
import { getHoldings, getPortfolioRisk } from '@/services/api'
import type { HoldingRow, PortfolioRisk, PortfolioSummary } from '@/types'

/** 持仓管理页: 持仓表格 + 风险仪表盘 + AI 持仓诊断（design 4.7.3 / 阶段8）。 */
export default function Portfolio() {
  const [holdings, setHoldings] = useState<HoldingRow[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [risk, setRisk] = useState<PortfolioRisk | null>(null)
  const [meta, setMeta] = useState<{ source?: string | null; as_of?: string | null; warnings?: string[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoadError(null)
    try {
      const resp = await getHoldings()
      setHoldings(resp.holdings)
      setSummary(resp.summary)
      setMeta(resp.data_meta ?? null)
      // 有持仓才拉风险评估（空列表直接置空态）
      setRisk(resp.summary.count > 0
        ? await getPortfolioRisk()
        : { incomplete: true, note: '无持仓，请先添加持仓', risk_level: null })
    } catch (err) {
      setLoadError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    reload().finally(() => setLoading(false))
  }, [reload])

  if (loading && holdings.length === 0 && !loadError) {
    return <PageLoading tip="正在加载持仓与风险数据..." />
  }
  if (loadError && holdings.length === 0) {
    return <PageError title="持仓数据加载失败" message={loadError} onRetry={reload} />
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      {loadError && (
        <Alert type="error" showIcon style={{ marginBottom: 10, fontSize: 12 }}
          message={`刷新失败: ${loadError}`} />
      )}
      {meta?.warnings && meta.warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 10, fontSize: 12 }}
          message={meta.warnings[0]} />
      )}
      {holdings.length === 0 ? (
        <div style={{ display: 'grid', placeItems: 'center', minHeight: '60%' }}>
          <Empty description="暂无持仓，点击下方按钮添加">
            <HoldingTable holdings={[]} summary={null} onReload={reload} />
          </Empty>
        </div>
      ) : (
        <>
          {meta?.source && (
            <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 8 }}>
              数据来源 {meta.source}
              {meta.as_of ? ` · 截至 ${meta.as_of}` : ''}
            </div>
          )}
          <HoldingTable holdings={holdings} summary={summary} onReload={reload} />
          <RiskDashboard risk={risk} />
          <AiAdviceCard enabled={!!summary && summary.count > 0 && !risk?.incomplete} />
        </>
      )}
    </div>
  )
}
