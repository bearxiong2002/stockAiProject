import { useEffect, useState } from 'react'
import { Empty, Spin, Tag, Typography } from 'antd'
import StockSearch from '@/components/StockSearch'
import { getRecentReports } from '@/services/api'
import type { RecentReportItem } from '@/services/api'
import type { StockBrief } from '@/types'

interface SearchPanelProps {
  onSelect: (stock: StockBrief) => void
}

/** 无报告时的居中大搜索面板 + 最近报告记录（report_history 全局最近）。 */
export default function SearchPanel({ onSelect }: SearchPanelProps) {
  const [recent, setRecent] = useState<RecentReportItem[] | null>(null)

  useEffect(() => {
    let alive = true
    getRecentReports(8)
      .then((r) => alive && setRecent(r.items))
      .catch(() => alive && setRecent([]))
    return () => {
      alive = false
    }
  }, [])

  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'flex-start', paddingTop: '14vh', gap: 28, height: '100%'
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <h2 style={{ fontSize: 22, marginBottom: 6 }}>股票分析报告</h2>
        <Typography.Text type="secondary">
          搜索代码或名称，生成技术面 / 基本面 / 资金面综合分析
        </Typography.Text>
      </div>
      <StockSearch size="large" style={{ width: 480 }} onSelect={onSelect} />
      <div style={{ width: 520, marginTop: 8 }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 8 }}>最近报告</div>
        {recent === null ? (
          <div style={{ textAlign: 'center' }}><Spin size="small" /></div>
        ) : recent.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无报告记录" />
        ) : (
          recent.map((r) => (
            <div
              key={r.id}
              onClick={() => onSelect({ code: r.stock_code, name: r.stock_name })}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '7px 10px', borderRadius: 6, cursor: 'pointer',
                background: 'var(--bg-container)', marginBottom: 6, border: '1px solid var(--border-color)'
              }}
            >
              <Tag color={r.score >= 10 ? 'red' : r.score <= -10 ? 'green' : 'default'}>
                {r.rating}
              </Tag>
              <strong style={{ width: 100, overflow: 'hidden' }}>{r.stock_name}</strong>
              <span style={{ color: 'var(--text-secondary)' }}>{r.stock_code}</span>
              <span style={{ marginLeft: 'auto', color: 'var(--text-secondary)', fontSize: 11 }}>
                {r.score > 0 ? '+' : ''}{r.score?.toFixed(1)} · {r.created_at?.slice(0, 16).replace('T', ' ')}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
