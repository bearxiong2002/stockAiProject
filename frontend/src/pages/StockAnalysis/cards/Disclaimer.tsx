import { Typography } from 'antd'

/** ⑧ 免责声明（固定文字）。 */
export default function Disclaimer({ text }: { text?: string }) {
  return (
    <Typography.Text
      type="secondary"
      style={{ display: 'block', textAlign: 'center', padding: '12px 0 18px', fontSize: 11 }}
    >
      {text ?? '本分析仅供参考，不构成投资建议，投资有风险，入市需谨慎'}
    </Typography.Text>
  )
}
