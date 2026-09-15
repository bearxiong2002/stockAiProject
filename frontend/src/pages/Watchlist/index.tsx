import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Empty, Popconfirm, Space, Spin, Table, Typography, message } from 'antd'
import { PageError, PageLoading } from '@/components/PageState'
import { ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import StockSearch from '@/components/StockSearch'
import { addWatchlist, getWatchlist, removeWatchlist } from '@/services/api'
import type { WatchlistItemView } from '@/types'

const UP = '#e0524d'
const DOWN = '#2eab68'

const pctCell = (v: number | null | undefined) => (
  <span style={{ color: v == null ? 'var(--text-secondary)' : v >= 0 ? UP : DOWN }}>
    {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`}
  </span>
)

/** 自选股看板（design 4.8）: 搜索添加 + 排序表格 + 移除/生成报告。 */
export default function Watchlist() {
  const [items, setItems] = useState<WatchlistItemView[]>([])
  const [meta, setMeta] = useState<{ source?: string | null; as_of?: string | null; warnings?: string[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const navigate = useNavigate()

  const reload = useCallback(async () => {
    setLoadError(null)
    try {
      const resp = await getWatchlist()
      setItems(resp.items)
      setMeta(resp.data_meta ?? null)
    } catch (err) {
      setLoadError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    reload().finally(() => setLoading(false))
  }, [reload])

  const add = async (code: string) => {
    try {
      setAdding(true)
      await addWatchlist(code)
      message.success(`已加入自选 ${code}`)
      await reload()
    } catch (err) {
      message.error(`添加失败: ${(err as Error).message}`)
    } finally {
      setAdding(false)
    }
  }

  const remove = async (code: string) => {
    await removeWatchlist(code)
    message.success('已移除')
    await reload()
  }

  if (loading && items.length === 0 && !loadError) {
    return <PageLoading tip="正在加载自选股行情..." />
  }
  if (loadError && items.length === 0) {
    return <PageError title="自选股加载失败" message={loadError} onRetry={reload} />
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '14px 18px' }}>
      <Space size={12} style={{ marginBottom: 12 }} align="center">
        <StockSearch
          style={{ width: 340 }}
          placeholder="搜索并加入自选"
          onSelect={(s) => add(s.code)}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新行情</Button>
        {adding && <Spin size="small" />}
      </Space>
      {loadError && (
        <Alert type="error" showIcon style={{ marginBottom: 10, fontSize: 12 }}
          message={`刷新失败: ${loadError}`} />
      )}
      {meta?.warnings && meta.warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 10, fontSize: 12 }}
          message={meta.warnings[0]} />
      )}
      <Table
        rowKey="id"
        size="small"
        dataSource={items}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无自选股，从上方搜索添加" /> }}
        columns={[
          { title: '代码', dataIndex: 'code', key: 'code', width: 90,
            sorter: (a, b) => a.code.localeCompare(b.code),
            render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
          { title: '名称', key: 'name', width: 120,
            render: (_, r) => r.name ?? r.stock_name ?? '—' },
          { title: '最新价', dataIndex: 'latest_price', key: 'price', width: 90,
            sorter: (a, b) => (a.latest_price ?? 0) - (b.latest_price ?? 0),
            render: (v: number | null) => (v == null ? '—' : v.toFixed(2)) },
          { title: '涨跌幅', dataIndex: 'pct_change', key: 'pct', width: 90,
            sorter: (a, b) => (a.pct_change ?? 0) - (b.pct_change ?? 0),
            render: pctCell },
          { title: '成交量(万手)', dataIndex: 'volume_wan', key: 'vol', width: 110,
            sorter: (a, b) => (a.volume_wan ?? 0) - (b.volume_wan ?? 0),
            render: (v: number | null) => (v == null ? '—' : v.toLocaleString()) },
          { title: '换手率', dataIndex: 'turnover', key: 'turnover', width: 90,
            sorter: (a, b) => (a.turnover ?? 0) - (b.turnover ?? 0),
            render: (v: number | null) => (v == null ? '—' : `${v.toFixed(2)}%`) },
          { title: 'PE', dataIndex: 'pe', key: 'pe', width: 80,
            sorter: (a, b) => (a.pe ?? 0) - (b.pe ?? 0),
            render: (v: number | null) => (v == null ? '—' : v.toFixed(2)) },
          { title: '行业', dataIndex: 'industry', key: 'industry', width: 110 },
          { title: '行情日', dataIndex: 'trade_date', key: 'date', width: 100 },
          { title: '操作', key: 'op', width: 150,
            render: (_, r) => (
              <Space size={10}>
                <a onClick={() => navigate(`/analysis/${r.code}`)}>生成报告</a>
                <Popconfirm title={`移除 ${r.stock_name ?? r.code}？`}
                  onConfirm={() => remove(r.code)}>
                  <a style={{ color: DOWN }}>移除</a>
                </Popconfirm>
              </Space>
            ) }
        ]}
      />
    </div>
  )
}
