import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Descriptions, Popconfirm, Space, Typography, message } from 'antd'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { clearCache, getCacheStats } from '@/services/api'
import type { CacheStats } from '@/services/api'

/** 数据缓存: 文件数/总大小/目录 + 清空缓存。 */
export default function CacheCard() {
  const [stats, setStats] = useState<CacheStats | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setStats(await getCacheStats())
    } catch (err) {
      message.error(`缓存统计获取失败: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const clear = async () => {
    setLoading(true)
    try {
      const resp = await clearCache()
      message.success(`已清空缓存（删除 ${resp.removed_files} 个文件）`)
      await load()
    } catch (err) {
      message.error(`清空失败: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card
      title="数据缓存"
      size="small"
      extra={
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={load}>
          刷新
        </Button>
      }
    >
      <Descriptions column={1} size="small">
        <Descriptions.Item label="缓存文件">
          {stats ? `${stats.file_count} 个` : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="占用空间">
          {stats?.total_size_human ?? '—'}
        </Descriptions.Item>
        <Descriptions.Item label="缓存目录">
          <Typography.Text type="secondary" style={{ fontSize: 12 }} copyable>
            {stats?.cache_dir ?? '—'}
          </Typography.Text>
        </Descriptions.Item>
      </Descriptions>
      <Space>
        <Popconfirm
          title="清空全部数据缓存？"
          description="下次查询将重新从数据源拉取，不影响持仓/自选等本地数据。"
          onConfirm={clear}
        >
          <Button size="small" danger icon={<DeleteOutlined />} loading={loading}>
            清空缓存
          </Button>
        </Popconfirm>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          缓存仅影响行情数据获取速度，不影响数据库中的持仓、自选与报告历史。
        </Typography.Text>
      </Space>
    </Card>
  )
}
