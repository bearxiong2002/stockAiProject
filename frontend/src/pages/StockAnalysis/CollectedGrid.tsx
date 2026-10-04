import { useCallback, useEffect, useState } from 'react'
import { message, Modal, Pagination, Spin, Tag, Tooltip } from 'antd'
import {
  DatabaseOutlined,
  DeleteOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { deleteCollectData, getCollectedStocks, getCollectStatus, updateCollectData } from '@/services/api'
import type { CollectedStockItem } from '@/types'
import type { StockBrief } from '@/types'

interface CollectedGridProps {
  onSelect: (stock: StockBrief) => void
  refreshKey?: number
}

export default function CollectedGrid({ onSelect, refreshKey }: CollectedGridProps) {
  const [items, setItems] = useState<CollectedStockItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<Record<string, string>>({})
  const pageSize = 12

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const resp = await getCollectedStocks(p, pageSize)
      setItems(resp.items)
      setTotal(resp.total)
    } catch {
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(page)
  }, [page, load, refreshKey])

  const handleDelete = useCallback(async (code: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    Modal.confirm({
      title: '删除采集数据',
      content: `确定删除 ${name || code} 的所有K线数据？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await deleteCollectData(code)
          message.success(`已删除 ${res.removed} 条数据`)
          load(page)
        } catch {
          message.error('删除失败')
        }
      },
    })
  }, [load, page])

  const pollUpdate = useCallback((code: string) => {
    const timer = setInterval(async () => {
      try {
        const s = await getCollectStatus(code)
        if (s.status === 'collecting') {
          setUpdating((prev) => ({ ...prev, [code]: s.message }))
        } else {
          clearInterval(timer)
          setUpdating((prev) => {
            const next = { ...prev }
            delete next[code]
            return next
          })
          if (s.status === 'completed') {
            message.success(s.message)
          } else {
            message.error(s.message)
          }
          load(page)
        }
      } catch {
        clearInterval(timer)
        setUpdating((prev) => {
          const next = { ...prev }
          delete next[code]
          return next
        })
      }
    }, 2000)
  }, [load, page])

  const handleUpdate = useCallback(async (code: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (updating[code]) return
    try {
      const s = await updateCollectData(code, name)
      if (s.status === 'completed') {
        message.success(s.message)
        load(page)
      } else if (s.status === 'collecting') {
        setUpdating((prev) => ({ ...prev, [code]: s.message }))
        pollUpdate(code)
      } else {
        message.error(s.message)
      }
    } catch {
      message.error('更新失败')
    }
  }, [updating, load, page, pollUpdate])

  if (loading && items.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0' }}>
        <Spin size="small" />
      </div>
    )
  }

  if (!loading && total === 0) return null

  const formatTime = (t: string | null) => {
    if (!t) return '-'
    return t.slice(0, 10)
  }

  return (
    <div style={{ width: '100%', maxWidth: 580, marginTop: 16 }}>
      <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 8 }}>
        <DatabaseOutlined style={{ marginRight: 4 }} />
        已采集数据（{total} 只）
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {items.map((item) => {
          const isUpdating = !!updating[item.stock_code]
          return (
            <div
              key={`${item.stock_code}-${item.freq}`}
              onClick={() => !isUpdating && onSelect({ code: item.stock_code, name: item.stock_name })}
              style={{
                padding: '10px 12px',
                borderRadius: 6,
                cursor: isUpdating ? 'wait' : 'pointer',
                background: 'var(--bg-container)',
                border: '1px solid var(--border-color)',
                transition: 'border-color 0.2s, box-shadow 0.2s',
                position: 'relative',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--primary)'
                e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.08)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-color)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <strong style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 90 }}>
                  {item.stock_name || item.stock_code}
                </strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Tooltip title="更新到最新">
                    <SyncOutlined
                      spin={isUpdating}
                      style={{ fontSize: 12, color: 'var(--primary)', cursor: 'pointer' }}
                      onClick={(e) => handleUpdate(item.stock_code, item.stock_name, e)}
                    />
                  </Tooltip>
                  <Tooltip title="删除数据">
                    <DeleteOutlined
                      style={{ fontSize: 12, color: '#ff4d4f', cursor: 'pointer' }}
                      onClick={(e) => handleDelete(item.stock_code, item.stock_name, e)}
                    />
                  </Tooltip>
                </div>
              </div>
              {item.stock_name && (
                <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {item.stock_code}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
                <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {item.row_count.toLocaleString()} 条
                </span>
                <Tag color="green" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                  {item.freq}
                </Tag>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary, var(--text-secondary))', marginTop: 2, opacity: 0.7 }}>
                {formatTime(item.min_time)} ~ {formatTime(item.max_time)}
              </div>
              {isUpdating && (
                <div style={{ fontSize: 10, color: 'var(--primary)', marginTop: 4 }}>
                  {updating[item.stock_code]}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {total > pageSize && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Pagination
            size="small"
            current={page}
            total={total}
            pageSize={pageSize}
            onChange={(p) => setPage(p)}
            showSizeChanger={false}
          />
        </div>
      )}
    </div>
  )
}
