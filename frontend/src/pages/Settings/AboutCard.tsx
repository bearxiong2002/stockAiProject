import { Card, Descriptions, Tag, Typography } from 'antd'
import type { AppConfigResponse } from '@/types'

/** 关于: 版本号 / 技术栈 / 部署模式 / 数据目录。 */
export default function AboutCard({ config }: { config: AppConfigResponse | null }) {
  const app = config?.app
  return (
    <Card title="关于" size="small">
      <Descriptions column={1} size="small">
        <Descriptions.Item label="应用">
          StockPanel v{app?.version ?? '—'}
          <Tag color="red" style={{ marginLeft: 8 }}>仅供学习研究</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="技术栈">
          React 18 + TypeScript + Ant Design + ECharts / Python FastAPI + SQLite
        </Descriptions.Item>
        <Descriptions.Item label="运行模式">
          {app?.serve_static ? (
            <Tag color="success">生产模式（后端托管前端静态文件，端口 {app.server_port}）</Tag>
          ) : (
            <Tag color="blue">开发模式（Vite 5173 + 后端 {app?.server_port ?? 18900}）</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="数据目录">
          <Typography.Text type="secondary" style={{ fontSize: 12 }} copyable>
            {app?.data_dir ?? '—'}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="前端构建">
          {app?.frontend_built
            ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>{app.frontend_dist}</Typography.Text>
            : <Typography.Text type="warning" style={{ fontSize: 12 }}>
                未检测到构建产物，执行 `npm run build` 后可用生产模式
              </Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="项目文档">
          docs/design.md · docs/implementation-plan.md · docs/startup.md
        </Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginTop: 8, marginBottom: 0 }}>
        本分析仅供参考，不构成投资建议，投资有风险，入市需谨慎。
      </Typography.Paragraph>
    </Card>
  )
}
