import { Alert, Card, Collapse, Descriptions, Space, Table, Tag, Typography } from 'antd'
import type { DataSourceStatus } from '@/types'

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  verified: { color: 'success', text: '已验证' },
  degraded: { color: 'warning', text: '降级' },
  unavailable: { color: 'error', text: '不可用' }
}

const PROVIDER_LABELS: Record<string, string> = {
  datahubco: 'Datahubco 基础版',
  promax: 'ProMax Relay'
}

/** 股票数据源状态（阶段 3 状态接口整合）: 模式/密钥状态/能力验证结论。 */
export default function DataSourceCard({ status }: { status: DataSourceStatus | null }) {
  const validation = status?.capability_validation
  const summary = validation?.summary
  const problems = (validation?.results ?? []).filter((r) => r.status !== 'verified')

  return (
    <Card
      title="股票数据源状态"
      size="small"
      extra={
        status ? (
          <Tag color="blue">模式: {status.mode}</Tag>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>加载中...</Typography.Text>
        )
      }
    >
      {!status ? null : (
        <>
          <Descriptions column={1} size="small" style={{ marginBottom: 10 }}>
            {Object.entries(status.providers ?? {}).map(([key, p]) => (
              <Descriptions.Item key={key} label={PROVIDER_LABELS[key] ?? key}>
                <Space size={8} wrap>
                  <Tag color={p.configured ? 'success' : 'default'}>
                    {p.configured ? '密钥已配置' : '密钥未配置'}
                  </Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {p.base_url}
                  </Typography.Text>
                  {p.transport_http && (
                    <Tag color={p.allow_http ? 'warning' : 'error'}>
                      {p.allow_http ? 'HTTP 明文（已允许）' : 'HTTP 明文未允许'}
                    </Tag>
                  )}
                  {(p.config_problems ?? []).map((problem) => (
                    <Tag key={problem} color="error">{problem}</Tag>
                  ))}
                </Space>
              </Descriptions.Item>
            ))}
          </Descriptions>
          {validation ? (
            <>
              <Space size={10} style={{ marginBottom: 6 }} wrap>
                <Typography.Text style={{ fontSize: 12 }}>
                  能力验证（{validation.generated_at?.replace('T', ' ') || '—'}）:
                </Typography.Text>
                <Tag color="success">通过 {summary?.verified ?? 0}</Tag>
                <Tag color={summary?.degraded ? 'warning' : 'default'}>
                  降级 {summary?.degraded ?? 0}
                </Tag>
                <Tag color={summary?.unavailable ? 'error' : 'default'}>
                  不可用 {summary?.unavailable ?? 0}
                </Tag>
              </Space>
              {problems.length === 0 ? (
                <Alert type="success" showIcon style={{ fontSize: 12 }}
                  message="全部能力验证通过，无降级项" />
              ) : (
                <Collapse
                  size="small"
                  items={[
                    {
                      key: 'problems',
                      label: `${problems.length} 项降级/不可用能力`,
                      children: (
                        <Table
                          rowKey="method"
                          size="small"
                          pagination={false}
                          dataSource={problems}
                          columns={[
                            { title: '能力', dataIndex: 'method', key: 'method' },
                            {
                              title: '状态',
                              dataIndex: 'status',
                              key: 'status',
                              width: 90,
                              render: (v: string) => (
                                <Tag color={STATUS_TAG[v]?.color ?? 'default'}>
                                  {STATUS_TAG[v]?.text ?? v}
                                </Tag>
                              )
                            },
                            { title: '说明', dataIndex: 'detail', key: 'detail' }
                          ]}
                        />
                      )
                    }
                  ]}
                />
              )}
            </>
          ) : (
            <Alert
              type="info"
              showIcon
              style={{ fontSize: 12 }}
              message="尚无能力验证记录"
              description="运行 backend/tests/smoke_real_apis.py（opt-in）后将写入验证结论，包含各接口的可用性与降级情况。"
            />
          )}
        </>
      )}
    </Card>
  )
}
