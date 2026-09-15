import { ReactNode } from 'react'
import { Button, Empty, Result, Spin, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

/** 统一加载态（Skeleton/Spin）：页面级数据加载中 */
export function PageLoading({ tip = '加载中...' }: { tip?: string }) {
  return (
    <div className="page-state">
      <div className="page-state-inner">
        <Spin size="large" />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{tip}</Typography.Text>
      </div>
    </div>
  )
}

/** 统一错误态：网络错误/后端错误友好提示 + 重试 */
export function PageError({
  title = '数据加载失败',
  message,
  onRetry
}: {
  title?: string
  message?: string | null
  onRetry?: () => void
}) {
  return (
    <div className="page-state">
      <div className="page-state-inner">
        <Result
          status="error"
          title={title}
          subTitle={message || '请确认后端服务运行正常后重试'}
          extra={
            onRetry ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={onRetry}>
                重试
              </Button>
            ) : undefined
          }
        />
      </div>
    </div>
  )
}

/** 统一空态：无数据时的引导内容 */
export function PageEmpty({
  description = '暂无数据',
  children
}: {
  description?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="page-state">
      <div className="page-state-inner">
        <Empty description={description}>{children}</Empty>
      </div>
    </div>
  )
}
