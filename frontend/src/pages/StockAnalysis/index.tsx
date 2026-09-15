import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Card, Progress, Typography, message } from 'antd'
import SearchPanel from './SearchPanel'
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
  const [progress, setProgress] = useState<ReportProgressEvent | null>(null)
  const [report, setReport] = useState<StockReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)

  const cancel = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
  }, [])

  const start = useCallback(
    (stock: StockBrief) => {
      cancel()
      setSelected(stock)
      setReport(null)
      setError(null)
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
    [cancel]
  )

  useEffect(() => cancel, [cancel])

  const generating = selected !== null && report === null && error === null
  const hasReportError = report !== null && !!report.error
  const pct = progress?.progress ?? 0

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      {selected === null && <SearchPanel onSelect={start} />}

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
        <Alert
          type="error"
          showIcon
          message={`报告生成失败`}
          description={error}
          style={{ maxWidth: 560, margin: '80px auto' }}
        />
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
