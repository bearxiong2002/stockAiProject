import { useState } from 'react'
import { Button, InputNumber, Modal, Popconfirm, Space, Table, Typography, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import StockSearch from '@/components/StockSearch'
import { addHolding, removeHolding, updateHolding } from '@/services/api'
import type { HoldingRow, PortfolioSummary, StockBrief } from '@/types'

const UP = '#e0524d'
const DOWN = '#2eab68'
const money = (v: number | null | undefined) =>
  v == null ? '—' : v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })

interface HoldingTableProps {
  holdings: HoldingRow[]
  summary: PortfolioSummary | null
  onReload: () => void
}

/** 上半部分: 可编辑持仓表格（添加弹窗/行内编辑/删除确认/汇总行）。 */
export default function HoldingTable({ holdings, summary, onReload }: HoldingTableProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [picked, setPicked] = useState<StockBrief | null>(null)
  const [qty, setQty] = useState<number>(100)
  const [cost, setCost] = useState<number | null>(null)
  const [buyDate, setBuyDate] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const openAdd = () => {
    setPicked(null)
    setQty(100)
    setCost(null)
    setBuyDate(null)
    setModalOpen(true)
  }

  const submitAdd = async () => {
    if (!picked) {
      message.warning('请先选择股票')
      return
    }
    if (!cost || cost <= 0 || qty <= 0) {
      message.warning('请填写有效的数量与成本价')
      return
    }
    try {
      setSaving(true)
      await addHolding({
        stock_code: picked.code,
        stock_name: picked.name,
        quantity: qty,
        cost_price: cost,
        buy_date: buyDate ?? undefined
      })
      message.success(`已添加 ${picked.name}`)
      setModalOpen(false)
      onReload()
    } catch (err) {
      message.error(`添加失败: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async (id: number, field: 'quantity' | 'cost_price', value: number | null) => {
    if (value == null || value <= 0) return
    await updateHolding(id, { [field]: value })
    onReload()
  }

  const remove = async (id: number) => {
    await removeHolding(id)
    message.success('已删除')
    onReload()
  }

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <Typography.Text strong style={{ fontSize: 14 }}>持仓</Typography.Text>
        <Button icon={<PlusOutlined />} onClick={openAdd}>添加持仓</Button>
      </div>
      <Table
        rowKey="id"
        size="small"
        dataSource={holdings}
        pagination={false}
        scroll={{ x: 1120 }}
        columns={[
          { title: '代码', dataIndex: 'stock_code', key: 'code', width: 90,
            render: (v: string) => <Typography.Text code style={{ whiteSpace: 'nowrap' }}>{v}</Typography.Text> },
          { title: '名称', dataIndex: 'stock_name', key: 'name', width: 100 },
          { title: '数量', dataIndex: 'quantity', key: 'qty', width: 120,
            render: (v: number, r) => (
              <InputNumber size="small" min={1} defaultValue={v}
                onBlur={(e) => { const x = Number(e.target.value); if (x > 0 && x !== v) saveEdit(r.id, 'quantity', x) }} />
            ) },
          { title: '成本价', dataIndex: 'cost_price', key: 'cost', width: 120,
            render: (v: number, r) => (
              <InputNumber size="small" min={0.01} step={0.01} defaultValue={v}
                onBlur={(e) => { const x = Number(e.target.value); if (x > 0 && x !== v) saveEdit(r.id, 'cost_price', x) }} />
            ) },
          { title: '现价', dataIndex: 'latest_price', key: 'price', width: 90,
            render: money },
          { title: '市值', dataIndex: 'market_value', key: 'mv', width: 100,
            render: money },
          { title: '盈亏', dataIndex: 'profit', key: 'profit', width: 100,
            render: (v: number | null) => (
              <span style={{ color: v == null ? 'var(--text-secondary)' : v >= 0 ? UP : DOWN }}>
                {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toLocaleString()}`}
              </span>
            ) },
          { title: '盈亏率', dataIndex: 'profit_pct', key: 'pct', width: 80,
            render: (v: number | null) => (
              <span style={{ color: v == null ? 'var(--text-secondary)' : v >= 0 ? UP : DOWN }}>
                {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`}
              </span>
            ) },
          { title: '占比', dataIndex: 'weight', key: 'weight', width: 70,
            render: (v: number | null) => (v == null ? '—' : `${v.toFixed(1)}%`) },
          { title: '持天', dataIndex: 'hold_days', key: 'days', width: 70,
            render: (v: number | null) => (v == null ? '—' : `${v}天`) },
          { title: '操作', key: 'op', width: 70,
            render: (_, r: HoldingRow) => (
              <Popconfirm title={`删除 ${r.stock_name}？`} onConfirm={() => remove(r.id)}>
                <a style={{ color: UP }}>删除</a>
              </Popconfirm>
            ) }
        ]}
        footer={() => summary ? (
          <Space size={22}>
            <span>总市值 <strong>{money(summary.total_market_value)}</strong></span>
            <span>总成本 <strong>{money(summary.total_cost)}</strong></span>
            <span>总盈亏 <strong style={{ color: summary.total_profit >= 0 ? UP : DOWN }}>
              {summary.total_profit >= 0 ? '+' : ''}{money(summary.total_profit)}
            </strong></span>
            <span>总盈亏率 <strong style={{ color: summary.total_profit_pct >= 0 ? UP : DOWN }}>
              {summary.total_profit_pct >= 0 ? '+' : ''}{summary.total_profit_pct?.toFixed(2)}%
            </strong></span>
          </Space>
        ) : null}
      />
      <Modal
        title="添加持仓"
        open={modalOpen}
        onOk={submitAdd}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <div style={{ marginBottom: 14 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 6 }}>选择股票</div>
          <StockSearch
            style={{ width: '100%' }}
            onSelect={(s) => setPicked(s)}
            placeholder="搜索代码或名称"
          />
          {picked && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              已选: {picked.name} {picked.code}
            </Typography.Text>
          )}
        </div>
        <Space size={16} wrap>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>数量（股）</div>
            <InputNumber min={1} value={qty} onChange={(v) => setQty(v ?? 100)} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>成本价</div>
            <InputNumber min={0.01} step={0.01} value={cost}
              onChange={(v) => setCost(v)} placeholder="每股成本" />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>买入日期（可选）</div>
            <input
              type="date"
              value={buyDate ?? ''}
              onChange={(e) => setBuyDate(e.target.value || null)}
              style={{
                background: 'var(--bg-elevated)', color: 'var(--text-primary)', border: '1px solid var(--border-color)',
                borderRadius: 6, padding: '4px 8px'
              }}
            />
          </div>
        </Space>
      </Modal>
    </>
  )
}
