export interface HealthResponse {
  status: string
  version: string
  app: string
}

export interface StockBrief {
  code: string
  name: string
  industry?: string
  market?: '沪' | '深' | '北'
}

// =====================================================================
// 阶段 4/5: 分析报告契约（对齐后端 design.md 6.2）
// ====================================================================

export interface KlineItem {
  date: string
  open: number | null
  close: number | null
  high: number | null
  low: number | null
  volume: number | null
  amount: number | null
  amplitude: number | null
  pct_change: number | null
  change: number | null
  turnover: number | null
}

export interface DataMeta {
  source?: string | null
  api?: string | null
  as_of?: string | null
  trade_date?: string | null
  fetched_at?: number | null
  is_stale?: boolean
  coverage?: Record<string, number>
  warnings?: string[]
  [key: string]: unknown
}

export interface TechSignal {
  indicator: string
  value: number | string | null
  signal: string
  direction: string
  note?: string
  crossed_at?: string | null
}

export interface TechComponent {
  score: number
  weight: number
  signals: TechSignal[]
}

export interface TechnicalResult {
  score: number | null
  rating: string | null
  incomplete: boolean
  components: Record<'trend' | 'oscillator' | 'channel' | 'volume', TechComponent>
  signals: TechSignal[]
  weights: Record<string, number>
  indicator_series?: IndicatorSeries
  data_meta?: DataMeta
}

export interface IndicatorSeries {
  dates: string[]
  ma: Record<string, (number | null)[]>
  macd: Record<'dif' | 'dea' | 'macd_hist', (number | null)[]>
  kdj: Record<'kdj_k' | 'kdj_d' | 'kdj_j', (number | null)[]>
  boll: Record<'boll_mid' | 'boll_upper' | 'boll_lower', (number | null)[]>
  volume: { volume: number[]; vol_ma_5: (number | null)[]; vol_ma_10: (number | null)[] }
}

export interface FundItem {
  name: string
  value: number | null
  industry_median?: number | null
  ratio?: number | null
  score: number | null
  note?: string
}

export interface FundSub {
  score: number
  weight: number
  items: FundItem[]
  max_possible: number
}

export interface FundamentalResult {
  score: number
  rating: string
  incomplete: boolean
  valuation: FundSub
  growth: FundSub
  health: FundSub
  data_meta?: DataMeta
}

export interface RatingResult {
  score: number | null
  level: string | null
  label: string | null
  action: string | null
  color: string | null
  weights: { technical: number; fundamental: number; sentiment: number | null } | null
  sentiment_score: number | null
  note?: string
}

export interface FundFlowBlock {
  main_net_inflow_5d: number | null
  trend: 'inflow' | 'outflow' | 'unknown'
  main_net_inflow_pct_5d?: number | null
  chart_data: Array<{
    date: string
    main_net_inflow: number
    main_net_inflow_pct: number | null
    super_large_net: number
    large_net: number
  }>
  note?: string
}

export type SentimentLabel = 'positive' | 'negative' | 'neutral'

export interface SentimentKeyEvent {
  event: string
  impact?: string
  sentiment: SentimentLabel
}

export interface NewsSentimentBlock {
  overall: string | null
  score: number | null
  key_events: SentimentKeyEvent[]
  summary?: string | null
  distribution?: { positive: number; negative: number; neutral: number } | null
  news_list: { title: string; content?: string; pub_time: string; source?: string }[]
  note?: string
}

/** AI 综合点评（阶段 8，design.md §4.4.2） */
export interface AiReport {
  summary: string
  technical_comment?: string
  fundamental_comment?: string
  risks: string[]
  catalysts: string[]
  recommendation?: string
}

/** AI 分析状态（provider/错误/权重，用于降级标注） */
export interface AiMeta {
  available: boolean
  provider?: string | null
  model?: string | null
  note?: string | null
  errors?: string[]
  generated?: boolean
  weights?: { technical: number; fundamental: number; sentiment: number | null } | null
}

export interface StockReport {
  stock_info: {
    code: string
    name: string | null
    industry: string | null
    market?: string | null
    market_cap: number | null
    latest_price: number | null
    pct_change: number | null
    trade_date: string | null
  }
  rating: RatingResult
  technical: TechnicalResult
  fundamental: FundamentalResult
  fund_flow: FundFlowBlock
  news_sentiment: NewsSentimentBlock
  ai_report: AiReport | null
  ai_meta?: AiMeta
  kline_data: KlineItem[]
  indicator_data: IndicatorSeries
  data_meta: DataMeta
  generated_at: string
  disclaimer?: string
  summary?: string
  error?: string
}

export interface ReportHistoryItem {
  id: number
  stock_name: string
  rating: string
  score: number
  summary: string | null
  created_at: string
}

export interface ReportProgressEvent {
  stage: string
  progress: number
  message: string
}

// =====================================================================
// 阶段 6: 持仓与风险
// ====================================================================

export interface HoldingRow {
  id: number
  stock_code: string
  stock_name: string
  quantity: number
  cost_price: number
  buy_date?: string | null
  notes?: string | null
  latest_price?: number | null
  market_value?: number | null
  profit?: number | null
  profit_pct?: number | null
  weight?: number | null
  hold_days?: number | null
  industry?: string | null
  trade_date?: string | null
}

export interface PortfolioSummary {
  total_market_value: number
  total_cost: number
  total_profit: number
  total_profit_pct: number
  count: number
}

export interface HoldingsResponse {
  holdings: HoldingRow[]
  summary: PortfolioSummary
  data_meta?: { source?: string | null; as_of?: string | null; warnings?: string[] }
}

export interface PortfolioRisk {
  incomplete?: boolean
  note?: string
  detail?: string
  total_market_value?: number
  sample_days?: number
  var?: {
    '95': { pct: number | null; amount: number | null; note?: string | null }
    '99': { pct: number | null; amount: number | null; note?: string | null }
  }
  max_drawdown?: { max: number | null; start: string | null; end: string | null; current: number | null }
  volatility?: { portfolio: number | null; index: number | null }
  beta?: number | null
  sharpe?: number | null
  concentration?: { hhi: number; top3_pct: number; level: string; count: number }
  sector_exposure?: { sectors: { industry: string; weight_pct: number; stock_codes: string[] }[]; count: number; warnings: string[] }
  correlation?: { codes: string[]; matrix: (number | null)[][]; high_pairs: { pair: string[]; corr: number }[] }
  portfolio_curve?: { dates: string[]; portfolio: number[]; benchmark: number[]; note?: string | null }
  risk_level?: string | null
  warnings?: string[]
}

// =====================================================================
// 阶段 7: 自选股与大盘概览
// ====================================================================

export interface WatchlistItemView {
  id: number
  code: string
  name?: string
  stock_name?: string
  latest_price?: number | null
  pct_change?: number | null
  volume_wan?: number | null
  turnover?: number | null
  pe?: number | null
  industry?: string | null
  trade_date?: string | null
  sort_order?: number
  error?: string
}

export interface MarketIndexItem {
  code: string
  name: string
  close?: number | null
  pct_change?: number | null
  amount_yi?: number | null
  trade_date?: string | null
  sparkline?: number[]
  index_kline?: null
  error?: string
}

export interface SectorItem {
  name: string
  code: string
  pct_change: number | null
  turnover: number | null
  amount_yi: number | null
  leading_stock: string | null
  leading_pct: number | null
}

export interface MarketFundFlowItem {
  date: string
  main_net_inflow: number
  main_net_inflow_pct: number | null
  super_large_net: number | null
  large_net: number | null
  medium_net: number | null
  small_net: number | null
}

export interface MarketStatistics {
  as_of?: string | null
  total?: number | null
  up?: number | null
  down?: number | null
  flat?: number | null
  limit_up?: number | null
  limit_down?: number | null
  note?: string | null
}

// =====================================================================
// 阶段 8: AI 诊断 / 系统配置 / 数据源状态
// ====================================================================

export interface PortfolioAiAdvice {
  available: boolean
  advice: {
    overall_assessment: string
    risk_warnings: string[]
    suggestions: string[]
    rebalance_ideas: string[]
  } | null
  provider?: string | null
  model?: string | null
  risk_level?: string | null
  generated_at?: string | null
  llm_configured?: boolean
  note?: string | null
  error?: unknown
  cached?: boolean
}

export interface LLMConfigView {
  provider: 'claude' | 'openai' | 'custom' | 'none'
  available: boolean
  disabled_reason?: string | null
  model: string
  api_base: string
  api_key_configured: boolean
  api_key_masked: string
  sources?: Record<string, string>
}

export interface AppInfoView {
  version: string
  server_port: number
  data_dir: string
  serve_static: boolean
  frontend_dist: string
  frontend_built: boolean
}

export interface LLMDefaults {
  default_bases: Record<string, string>
  default_models: Record<string, string>
  model_suggestions: Record<string, string[]>
  providers: string[]
}

export interface AppConfigResponse {
  app: AppInfoView
  llm: LLMConfigView
  llm_defaults: LLMDefaults
}

export interface LLMTestResult {
  ok: boolean
  category?: string | null
  error?: string | null
  provider?: string | null
  model?: string | null
  latency_ms?: number | null
  reply?: string | null
}

export interface DataSourceCapabilityResult {
  method: string
  status: 'verified' | 'degraded' | 'unavailable' | string
  detail?: string | null
  rows?: number | null
  trade_date?: string | null
  source?: string | null
  elapsed_ms?: number | null
}

export interface DataSourceStatus {
  mode: string
  providers: Record<
    string,
    {
      configured: boolean
      base_url: string
      transport_http?: boolean
      allow_http?: boolean
      config_problems?: string[]
    }
  >
  capability_validation: {
    generated_at: string
    mode?: string
    summary?: { verified: number; degraded: number; unavailable: number }
    results: DataSourceCapabilityResult[]
  } | null
}
