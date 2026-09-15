import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Empty, Space, Spin, Tag, Typography } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  SwapOutlined
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { getPortfolioAiAdvice } from '@/services/api'
import type { PortfolioAiAdvice } from '@/types'

const UP = '#e0524d'
const DOWN = '#2eab68'

/** AI 持仓诊断卡片（阶段8，design.md §6.3）: 总体评估 + 风险警示 + 建议 + 调仓思路。 */
export default function AiAdviceCard({ enabled }: { enabled: boolean }) {
  const [data, setData] = useState<PortfolioAiAdvice | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (force = false) => {
      if (!enabled) return
      setLoading(true)
      setError(null)
      try {
        setData(await getPortfolioAiAdvice(force))
      } catch (err) {
        setError((err as Error).message)
      } finally {
        setLoading(false)
      }
    },
    [enabled]
  )

  useEffect(() => {
    if (enabled) void load()
  }, [enabled, load])

  if (!enabled) return null

  const advice = data?.available ? data.advice : null

  return (
    <Card
      size="small"
      title="AI 持仓诊断"
      style={{ marginTop: 12 }}
      styles={{ body: { padding: '12px 16px' } }}
      extra={
        <Space size={8}>
          {data?.available && (
            <Tag color="purple" style={{ fontSize: 10 }}>
              {data.provider}/{data.model}
            </Tag>
          )}
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => load(true)}
          >
            重新生成
          </Button>
        </Space>
      }
    >
      {loading && !advice ? (
        <div style={{ display: 'grid', placeItems: 'center', minHeight: 80, gap: 8 }}>
          <Spin size="small" />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            AI 正在诊断组合（约数秒）...
          </Typography.Text>
        </div>
      ) : error ? (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>{error}</Typography.Text>
      ) : advice ? (
        <>
          <div style={{ fontSize: 13, lineHeight: 1.9 }}>{advice.overall_assessment}</div>
          {advice.risk_warnings?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
                风险警示
              </div>
              {advice.risk_warnings.map((w, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0' }}>
                  <CloseCircleOutlined style={{ color: UP, marginTop: 3, fontSize: 12 }} />
                  <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>{w}</span>
                </div>
              ))}
            </div>
          )}
          {advice.suggestions?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
                操作建议
              </div>
              {advice.suggestions.map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0' }}>
                  <CheckCircleOutlined style={{ color: DOWN, marginTop: 3, fontSize: 12 }} />
                  <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>{s}</span>
                </div>
              ))}
            </div>
          )}
          {advice.rebalance_ideas?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>
                调仓思路
              </div>
              {advice.rebalance_ideas.map((r, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0' }}>
                  <SwapOutlined style={{ color: '#4d9de0', marginTop: 3, fontSize: 12 }} />
                  <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>{r}</span>
                </div>
              ))}
            </div>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 10.5, display: 'block', marginTop: 10 }}>
            {data?.generated_at ? `生成于 ${data.generated_at.replace('T', ' ').slice(0, 16)}` : ''}
            {data?.cached ? ' · 命中 10 分钟缓存' : ''} · 仅供参考，不构成投资建议
          </Typography.Text>
        </>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span style={{ fontSize: 12 }}>{data?.note ?? '暂无 AI 诊断'}</span>}
        >
          {data?.llm_configured === false && (
            <Link to="/settings" style={{ fontSize: 12 }}>前往设置配置 AI</Link>
          )}
        </Empty>
      )}
    </Card>
  )
}
