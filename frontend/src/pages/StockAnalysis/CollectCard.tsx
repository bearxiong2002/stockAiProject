import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Card, Progress, Tag } from 'antd'
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  LoadingOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { checkCollectData, getCollectStatus, startCollect } from '@/services/api'
import type { CollectStatus, StockBrief } from '@/types'

interface CollectCardProps {
  stock: StockBrief
  years?: number
  freq?: string
  onComplete: (stock: StockBrief) => void
}

/** 日线采集卡片: 查库 → 自动采集 → 轮询进度 → 完成后自动生成报告。 */
export default function CollectCard({
  stock,
  years = 3,
  freq = 'daily',
  onComplete,
}: CollectCardProps) {
  const [status, setStatus] = useState<CollectStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const startPolling = useCallback(
    (code: string) => {
      stopPolling()
      timerRef.current = setInterval(async () => {
        try {
          const s = await getCollectStatus(code)
          setStatus(s)
          if (s.status === 'completed' || s.status === 'error') {
            stopPolling()
          }
        } catch {
          // 网络错误忽略，继续轮询
        }
      }, 2000)
    },
    [stopPolling]
  )

  const doStart = useCallback(async () => {
    try {
      const s = await startCollect(stock.code, stock.name ?? '', years, freq)
      setStatus(s)
      if (s.status === 'collecting') {
        startPolling(stock.code)
      }
    } catch (err) {
      setStatus({
        stock_code: stock.code,
        stock_name: stock.name ?? '',
        freq,
        years,
        status: 'error',
        progress: 0,
        message: `启动失败: ${err instanceof Error ? err.message : String(err)}`,
        total_months: 0,
        fetched_months: 0,
        total_rows: 0,
        error: String(err),
      })
    }
  }, [stock, years, freq, startPolling])

  // 挂载时：先查进行中任务 / 已有数据，无数据才自动启动采集
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const taskStatus = await getCollectStatus(stock.code)
        if (alive && taskStatus.status === 'collecting') {
          setStatus(taskStatus)
          setChecking(false)
          startPolling(stock.code)
          return
        }
        if (alive && taskStatus.status === 'completed') {
          setStatus(taskStatus)
          setChecking(false)
          return
        }
        const check = await checkCollectData(stock.code, freq)
        if (alive && check.exists && check.row_count > 0) {
          setStatus({
            stock_code: stock.code,
            stock_name: stock.name ?? '',
            freq,
            years,
            status: 'completed',
            progress: 100,
            message: `数据已就绪（${check.row_count.toLocaleString()} 条）`,
            total_months: 0,
            fetched_months: 0,
            total_rows: check.row_count,
            error: null,
          })
          setChecking(false)
          return
        }
        if (alive) {
          setChecking(false)
          await doStart()
        }
      } catch {
        // 查询失败不阻塞流程，直接尝试启动采集
        if (alive) {
          setChecking(false)
          await doStart()
        }
      }
    })()
    return () => {
      alive = false
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stock.code])

  if (checking) {
    return (
      <Card size="small" style={{ marginTop: 16 }}>
        <LoadingOutlined style={{ marginRight: 8 }} />
        检查 {stock.name}（{stock.code}）的历史数据...
      </Card>
    )
  }

  if (!status) return null

  const isCollecting = status.status === 'collecting'
  const isCompleted = status.status === 'completed'
  const isError = status.status === 'error'

  return (
    <Card
      size="small"
      style={{
        marginTop: 16,
        border: isCompleted
          ? '1px solid #52c41a'
          : isError
            ? '1px solid #ff4d4f'
            : '1px solid var(--border-color)',
        cursor: isCompleted ? 'pointer' : 'default',
      }}
      onClick={isCompleted ? () => onComplete(stock) : undefined}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <DatabaseOutlined style={{ fontSize: 18 }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <strong>{stock.name}</strong>
            <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
              {stock.code}
            </span>
            <Tag color={isCompleted ? 'green' : isError ? 'red' : 'blue'}>
              {freq} · {years}年
            </Tag>
          </div>

          {isCollecting && (
            <div style={{ marginTop: 8 }}>
              <Progress
                percent={status.progress}
                size="small"
                status="active"
                strokeColor="var(--primary)"
              />
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                {status.message}
                {status.total_rows > 0 && ` · 已入库 ${status.total_rows.toLocaleString()} 条`}
              </div>
            </div>
          )}

          {isCompleted && (
            <div style={{ marginTop: 4, fontSize: 12 }}>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
              {status.message}
              <span style={{ color: 'var(--primary)', marginLeft: 8 }}>
                点击生成分析报告 →
              </span>
            </div>
          )}

          {isError && (
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 12, color: '#ff4d4f' }}>
                <WarningOutlined style={{ marginRight: 4 }} />
                {status.message}
              </div>
              <Button
                size="small"
                style={{ marginTop: 6 }}
                onClick={(e) => {
                  e.stopPropagation()
                  doStart()
                }}
              >
                重试
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
