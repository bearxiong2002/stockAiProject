import { CSSProperties, useEffect, useRef, useState } from 'react'
import { AutoComplete, Input, Spin, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { getStockList } from '@/services/api'
import type { StockBrief } from '@/types'

/**
 * 股票搜索组件（design.md 4.6.3）
 *
 * - 启动时一次性加载全部股票列表到内存（模块级缓存，多实例共享）
 * - 输入时前端本地过滤（代码前缀 / 名称包含），无网络请求
 * - debounce 300ms；下拉展示 代码 + 名称 + 行业
 */
let stockListCache: StockBrief[] | null = null
let stockListPromise: Promise<StockBrief[]> | null = null

function loadStockList(): Promise<StockBrief[]> {
  if (stockListCache) return Promise.resolve(stockListCache)
  stockListPromise ??= getStockList()
    .then((list) => {
      stockListCache = list
      return list
    })
    .catch((err) => {
      stockListPromise = null // 失败后允许重试
      throw err
    })
  return stockListPromise
}

/** 本地过滤: 代码前缀或名称包含，最多 limit 条 */
export function matchStocks(list: StockBrief[], keyword: string, limit = 20): StockBrief[] {
  const q = keyword.trim().toLowerCase()
  if (!q) return []
  return list
    .filter((s) => s.code.startsWith(q) || s.name.toLowerCase().includes(q))
    .slice(0, limit)
}

interface StockSearchProps {
  /** 选中某只股票时回调 */
  onSelect?: (stock: StockBrief) => void
  placeholder?: string
  size?: 'small' | 'middle' | 'large'
  style?: CSSProperties
}

export default function StockSearch({
  onSelect,
  placeholder = '搜索代码或名称，如 600519 / 茅台',
  size = 'middle',
  style
}: StockSearchProps) {
  const [stocks, setStocks] = useState<StockBrief[]>([])
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [matched, setMatched] = useState<StockBrief[]>([])
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let alive = true
    loadStockList()
      .then((list) => {
        if (alive) {
          setStocks(list)
          setLoading(false)
        }
      })
      .catch(() => {
        if (alive) {
          setLoading(false)
          message.error('股票列表加载失败，请确认后端已启动')
        }
      })
    return () => {
      alive = false
    }
  }, [])

  const handleChange = (value: string) => {
    setKeyword(value)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setMatched(matchStocks(stocks, value)), 300)
  }

  const options = matched.map((s) => ({
    value: s.code,
    label: (
      <span className="stock-search-option">
        <span className="stock-search-code">{s.code}</span>
        <span className="stock-search-name">{s.name}</span>
        <span className="stock-search-industry">{s.industry ?? ''}</span>
      </span>
    )
  }))

  return (
    <AutoComplete
      value={keyword}
      options={options}
      onChange={handleChange}
      onSelect={(code: string) => {
        const stock = matched.find((s) => s.code === code)
        if (stock) onSelect?.(stock)
      }}
      style={{ width: 320, ...style }}
      popupMatchSelectWidth={380}
      notFoundContent={
        loading ? <Spin size="small" /> : keyword.trim() ? '无匹配结果' : null
      }
    >
      <Input prefix={<SearchOutlined />} placeholder={placeholder} size={size} allowClear />
    </AutoComplete>
  )
}
