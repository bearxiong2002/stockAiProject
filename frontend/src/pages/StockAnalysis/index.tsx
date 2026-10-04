import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Card } from 'antd'
import SearchPanel from './SearchPanel'
import CollectCard from './CollectCard'
import ReportView from './ReportView'
import { streamReport } from '@/services/api'
import type { ReportProgressEvent, StockBrief, StockReport } from '@/types'

const STAGE_LABELS: Record<string, string> = {
  fetching_data: '获取行情与基本面数据',
  technical_analysis: '计算技术指标',
  fundamental_analysis: '分析基本面',
  ai_analysis: 'AI 情绪分析',
  building_report: '生成报告',
  error: '生成失败'
}

export default function StockAnalysis() {
  const [selected, setSelected] = useState<StockBrief | null>(null)
  const [collecting, setCollecting] = useState(false)
  const [progress, setProgress] = useState<ReportProgressEvent | null>(null)
  const [report, setReport] = useState<StockReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)

  const cancel = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
  }, [])

  // 搜索面板点击：先采集日线数据
  const handleSelect = useCallback(
    (stock: StockBrief) => {
      cancel()
      setSelected(stock)
      setCollecting(true)
      setReport(null)
      setError(null)
      setProgress(null)
    },
    [cancel]
  )

  // 日线采集完成后自动生成报告
  const handleCollectComplete = useCallback(
    (stock: StockBrief) => {
      setCollecting(false)
      setProgress({ stage: 'fetching_data', progress: 5, message: '连接后端...' })
      cancelRef.current = streamReport(stock.code, {
        onProgress: (ev) => setProgress(ev),
        onReport: (r) => setReport(r),
        onError: (msg) => setError(msg),
        onComplete: () => {
          cancelRef.current = null
        }
      })
    },
    []
  )

  useEffect(() => cancel, [cancel])

  const generating = selected !== null && !collecting && report === null && error === null
  const hasReportError = report !== null && !!report.error
  const pct = progress?.progress ?? 0

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      {/* 搜索面板：无报告时显示 */}
      {selected === null && (
        <SearchPanel onSelect={handleSelect} />
      )}

      {/* 日线采集卡片 */}
      {selected && collecting && (
        <div style={{ maxWidth: 520, margin: '40px auto' }}>
          <div style={{ marginBottom: 10 }}>
            <a onClick={() => { setSelected(null); setCollecting(false) }} style={{ fontSize: 12 }}>
              ← 重新搜索
            </a>
          </div>
          <CollectCard stock={selected} onComplete={handleCollectComplete} />
        </div>
      )}

      {generating && (
        <div
          style={{
            height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          <Card style={{ width: 420, textAlign: 'center' }}>
            <h3 style={{ marginBottom: 16 }}>
              正在生成 {selected?.name}（{selected?.code}）报告
            </h3>
            <div style={{ position: 'relative', margin: '12px 0 6px' }}>
              <div style={{ height: 10, background: 'var(--bg-elevated)', borderRadius: 5, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${pct}%`, height: '100%', borderRadius: 5,
                    background: 'var(--primary)', transition: 'width 0.4s'
                  }}
                />
              </div>
              <div style={{ marginTop: 10, fontSize: 13 }}>{progress?.message}</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 4 }}>
                {STAGE_LABELS[progress?.stage ?? ''] ?? ''} · {pct}%
              </div>
            </div>
          </Card>
        </div>
      )}

      {error && (
        <>
          <div style={{ marginBottom: 10 }}>
            <a onClick={() => { setSelected(null); setError(null) }} style={{ fontSize: 12 }}>
              ← 重新搜索
            </a>
          </div>
          <Alert
            type="error"
            showIcon
            message={`报告生成失败`}
            description={error}
            style={{ maxWidth: 560, margin: '40px auto' }}
          />
        </>
      )}

      {hasReportError && (
        <>
          <div style={{ marginBottom: 10 }}>
            <a onClick={() => { setSelected(null); setReport(null) }} style={{ fontSize: 12 }}>
              ← 重新搜索
            </a>
          </div>
          <Alert
            type="error"
            showIcon
            message="报告生成失败"
            description={report!.error}
            style={{ maxWidth: 560, margin: '40px auto' }}
          />
        </>
      )}

      {report && !hasReportError && (
        <>
          <div style={{ marginBottom: 10 }}>
            <a
              onClick={() => {
                setSelected(null)
                setReport(null)
              }}
              style={{ fontSize: 12 }}
            >
              ← 重新搜索
            </a>
          </div>
          <ReportView report={report} />
        </>
      )}
    </div>
  )
}
