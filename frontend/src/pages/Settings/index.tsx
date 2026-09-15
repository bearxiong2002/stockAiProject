import { useCallback, useEffect, useState } from 'react'
import { Space, Typography, message } from 'antd'
import DataSourceCard from './DataSourceCard'
import AIConfigCard from './AIConfigCard'
import CacheCard from './CacheCard'
import AboutCard from './AboutCard'
import { PageError, PageLoading } from '@/components/PageState'
import { getAppConfig, getDataSourceStatus } from '@/services/api'
import type { AppConfigResponse, DataSourceStatus } from '@/types'

/** 设置页（阶段8）: 数据源状态 / AI 配置 / 缓存管理 / 关于。 */
export default function Settings() {
  const [config, setConfig] = useState<AppConfigResponse | null>(null)
  const [dataSource, setDataSource] = useState<DataSourceStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [cfg, ds] = await Promise.all([getAppConfig(), getDataSourceStatus()])
      setConfig(cfg)
      setDataSource(ds)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
      .catch((err) => message.error((err as Error).message))
      .finally(() => setLoading(false))
  }, [load])

  if (loading && !config) return <PageLoading tip="正在读取配置..." />
  if (error && !config) return <PageError message={error} onRetry={load} />

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Text strong style={{ fontSize: 15 }}>设置</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          股票数据源密钥由后端环境变量/.env 管理；AI 密钥在此配置并加密存储
        </Typography.Text>
      </div>
      <Space direction="vertical" size={12} style={{ display: 'flex', marginTop: 12 }}>
        <DataSourceCard status={dataSource} />
        <AIConfigCard config={config} onChanged={load} />
        <CacheCard />
        <AboutCard config={config} />
      </Space>
    </div>
  )
}
