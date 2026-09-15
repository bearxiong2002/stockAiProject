import { ReactNode, useEffect } from 'react'
import { Result, Spin, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useBackendStore } from '@/stores/backend'

/** 后端就绪前阻塞页面渲染，等待期间显示 loading 画面 */
export default function BackendGate({ children }: { children: ReactNode }) {
  const { status, probeOnce } = useBackendStore()

  useEffect(() => {
    void probeOnce()
  }, [probeOnce])

  if (status === 'connecting') {
    return (
      <div className="boot-screen">
        <Spin size="large" />
        <div className="boot-screen-title">StockPanel</div>
        <div className="boot-screen-sub">正在启动 Python 后端服务...</div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="boot-screen">
        <Result
          status="error"
          title="后端服务连接失败"
          subTitle="Python 后端未能在 30 秒内就绪，请检查依赖安装后重试。"
          extra={
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={() => {
                useBackendStore.setState({ status: 'connecting' })
                void probeOnce(10000)
              }}
            >
              重试
            </Button>
          }
        />
      </div>
    )
  }

  return <>{children}</>
}
