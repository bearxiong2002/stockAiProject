import { Col, Row, Spin } from 'antd'
import HeaderCard from './cards/HeaderCard'
import ChartSection from './cards/ChartSection'
import TechnicalCard from './cards/TechnicalCard'
import FundamentalCard from './cards/FundamentalCard'
import FundFlowCard from './cards/FundFlowCard'
import SentimentCard from './cards/SentimentCard'
import ConclusionCard from './cards/ConclusionCard'
import Disclaimer from './cards/Disclaimer'
import type { StockReport } from '@/types'

/** 报告展示: design.md 4.6.2 的 8 个区块卡片式布局。 */
export default function ReportView({ report }: { report: StockReport }) {
  if (report.error) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
        <div style={{ marginTop: 12, color: 'var(--text-secondary)' }}>{report.error}</div>
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingBottom: 8 }}>
      <HeaderCard report={report} />
      <ChartSection report={report} />
      <Row gutter={12}>
        <Col xs={24} xl={12}>
          <TechnicalCard report={report} />
        </Col>
        <Col xs={24} xl={12}>
          <FundamentalCard report={report} />
        </Col>
      </Row>
      <Row gutter={12}>
        <Col xs={24} xl={12}>
          <FundFlowCard report={report} />
        </Col>
        <Col xs={24} xl={12}>
          <SentimentCard report={report} />
        </Col>
      </Row>
      <ConclusionCard report={report} />
      <Disclaimer text={report.disclaimer} />
    </div>
  )
}
