import { useEffect, useState } from 'react'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
  message
} from 'antd'
import { ApiOutlined, SaveOutlined } from '@ant-design/icons'
import { testLLM, updateAppConfig } from '@/services/api'
import type { AppConfigResponse } from '@/types'

const PROVIDER_OPTIONS = [
  { value: 'none', label: '不使用 AI（纯算法评分 50/50）' },
  { value: 'claude', label: 'Claude（Anthropic）' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'custom', label: '自定义（OpenAI 兼容）' }
]

interface FormValues {
  provider: string
  api_key?: string
  api_base?: string
  model?: string
}

/** AI/LLM 配置: Provider / API Key（密码框）/ Base URL / Model / 测试连接。 */
export default function AIConfigCard({
  config,
  onChanged
}: {
  config: AppConfigResponse | null
  onChanged: () => void
}) {
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const llm = config?.llm
  const defaults = config?.llm_defaults

  useEffect(() => {
    if (!config) return
    form.setFieldsValue({
      provider: config.llm.provider,
      api_key: '',
      api_base: config.llm.api_base,
      model: config.llm.model
    })
  }, [config, form])

  const provider = Form.useWatch('provider', form) ?? 'none'
  const disabled = provider === 'none'

  const save = async (values: FormValues) => {
    setSaving(true)
    try {
      // 密钥留空 = 保持不变（不发送该字段）；其余字段空串 = 清空
      const payload: Parameters<typeof updateAppConfig>[0] = {
        llm_provider: values.provider,
        llm_api_base: values.api_base ?? '',
        llm_model: values.model ?? ''
      }
      if (values.api_key) payload.llm_api_key = values.api_key
      const resp = await updateAppConfig(payload)
      if (resp.llm.available || resp.llm.provider === 'none') {
        message.success('AI 配置已保存')
      } else {
        message.warning(`已保存，但尚不可用: ${resp.llm.disabled_reason ?? '配置不完整'}`)
      }
      form.setFieldValue('api_key', '')
      onChanged()
    } catch (err) {
      message.error(`保存失败: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  const runTest = async () => {
    const values = form.getFieldsValue()
    if (values.provider === 'none') {
      message.warning('请先选择 LLM Provider')
      return
    }
    setTesting(true)
    try {
      const result = await testLLM({
        provider: values.provider,
        api_key: values.api_key || undefined,
        api_base: values.api_base || undefined,
        model: values.model || undefined
      })
      if (result.ok) {
        message.success(
          `连接成功（${result.provider} / ${result.model}，${result.latency_ms}ms）`
        )
      } else {
        message.error(`连接失败[${result.category ?? 'unknown'}]: ${result.error ?? '未知错误'}`)
      }
    } catch (err) {
      message.error(`测试请求失败: ${(err as Error).message}`)
    } finally {
      setTesting(false)
    }
  }

  const clearKey = async () => {
    setSaving(true)
    try {
      await updateAppConfig({ clear_api_key: true })
      message.success('已清除 API Key')
      onChanged()
    } catch (err) {
      message.error(`清除失败: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="AI 配置"
      size="small"
      extra={
        llm ? (
          <Space size={6}>
            <Tag color={llm.available ? 'success' : 'default'}>
              {llm.available ? 'AI 已启用' : 'AI 未启用'}
            </Tag>
            {llm.api_key_configured && (
              <Tag color="blue">密钥 {llm.api_key_masked}</Tag>
            )}
          </Space>
        ) : null
      }
    >
      {llm && !llm.available && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12, fontSize: 12 }}
          message={llm.disabled_reason ?? '未配置 AI'}
          description="未配置时报告仍可正常生成：综合评分回退技术面/基本面 50/50 权重，并在报告中标注“AI 分析不可用”。"
        />
      )}
      <Form
        form={form}
        layout="vertical"
        size="small"
        initialValues={{ provider: 'none' }}
        onFinish={save}
        style={{ maxWidth: 620 }}
      >
        <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
          <Select options={PROVIDER_OPTIONS} onChange={() => form.setFieldValue('api_key', '')} />
        </Form.Item>

        <Form.Item
          name="api_key"
          label="API Key"
          extra={
            llm?.api_key_configured
              ? `已保存（${llm.api_key_masked}，加密存储）。留空表示不修改。`
              : '密钥仅保存在本机（加密存储），不会回显明文。'
          }
        >
          <Input.Password
            disabled={disabled}
            autoComplete="new-password"
            placeholder={llm?.api_key_configured ? '留空保持现有密钥' : 'sk-...'}
          />
        </Form.Item>

        <Form.Item
          name="api_base"
          label="API Base URL（可选）"
          extra={defaults?.default_bases?.[provider]
            ? `留空使用默认: ${defaults.default_bases[provider]}`
            : '自定义/代理地址，如 http://localhost:11434/v1'}
        >
          <Input disabled={disabled} placeholder="https://..." />
        </Form.Item>

        <Form.Item
          name="model"
          label="Model"
          extra={defaults?.default_models?.[provider]
            ? `留空使用默认: ${defaults.default_models[provider]}`
            : undefined}
        >
          <AutoComplete
            disabled={disabled}
            options={(defaults?.model_suggestions?.[provider] ?? []).map((m) => ({
              value: m
            }))}
            placeholder="选择或输入模型名"
            filterOption={(input, option) =>
              String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Space>
          <Button
            type="primary"
            size="small"
            icon={<SaveOutlined />}
            htmlType="submit"
            loading={saving}
          >
            保存配置
          </Button>
          <Button
            size="small"
            icon={<ApiOutlined />}
            loading={testing}
            disabled={disabled}
            onClick={runTest}
          >
            测试连接
          </Button>
          {llm?.api_key_configured && (
            <Popconfirm title="清除已保存的 API Key？" onConfirm={clearKey}>
              <Button size="small" danger>清除密钥</Button>
            </Popconfirm>
          )}
        </Space>
        {llm?.sources?.provider === 'env' && (
          <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
            当前配置来自环境变量/.env；在此保存后将优先生效（SQLite 配置优先级更高）。
          </Typography.Text>
        )}
      </Form>
    </Card>
  )
}
