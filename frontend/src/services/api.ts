import axios from 'axios'
import type { CollectCheckResult, CollectStatus, StockBrief } from '@/types'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000
})

/** 后端错误体（DataSourceError/HTTPException）→ 可读文案 */
export function friendlyError(err: unknown): string {
  const error = err as {
    response?: { status?: number; data?: { detail?: unknown; error?: unknown } }
    message?: string
  }
  const data = error?.response?.data
  const detail = data?.detail
  if (typeof detail === 'string' && detail) return detail
  const biz = data?.error as { message?: string; code?: string } | string | undefined
  if (typeof biz === 'string' && biz) return biz
  if (biz && typeof biz === 'object' && biz.message) return biz.message
  const status = error?.response?.status
  if (status === 404) return '接口不存在（请确认后端版本）'
  if (status === 503) return '数据源不可用，请检查设置页数据源状态'
  if (status === 504) return '数据源请求超时，请稍后重试'
  if (status === 429) return '请求过于频繁，请稍后重试'
  if (status && status >= 500) return `后端错误（${status}），请查看后端日志`
  return error?.message || '网络错误，请确认后端服务已启动'
}

// 统一把错误转为带可读 message 的 Error（页面 catch 后直接展示）
api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (axios.isAxiosError(error)) {
      const friendly = friendlyError(error)
      if (friendly !== error.message) {
        error.message = friendly
      }
    }
    return Promise.reject(error)
  }
)

export type BackendStatus = 'connecting' | 'ready' | 'error'

export interface HealthResponse {
  status: string
  version: string
  app: string
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health', { timeout: 3000 })
  return data
}

// ---------- 股票搜索（阶段2） ----------

export async function getStockList(): Promise<StockBrief[]> {
  const { data } = await api.get<StockBrief[]>('/stock/list')
  return data
}

export async function searchStocks(q: string): Promise<StockBrief[]> {
  const { data } = await api.get<StockBrief[]>('/stock/search', { params: { q } })
  return data
}

// ---------- 缓存管理（阶段2） ----------

export interface CacheStats {
  file_count: number
  total_size: number
  total_size_human: string
  cache_dir: string
}

export async function getCacheStats(): Promise<CacheStats> {
  const { data } = await api.get<CacheStats>('/config/cache-stats')
  return data
}

export async function clearCache(): Promise<{ ok: boolean; removed_files: number }> {
  const { data } = await api.delete<{ ok: boolean; removed_files: number }>('/config/cache')
  return data
}

export default api

// =====================================================================
// 阶段 4/5: 技术分析 / 基本面 / 综合报告（SSE）
// ====================================================================

import type {
  FundamentalResult,
  ReportHistoryItem,
  ReportProgressEvent,
  StockReport,
  TechnicalResult
} from '@/types'

export async function getTechnical(code: string, days = 250): Promise<TechnicalResult> {
  const { data } = await api.get<TechnicalResult>(`/stock/${code}/technical`, {
    params: { days }
  })
  return data
}

export async function getFundamental(code: string): Promise<FundamentalResult> {
  const { data } = await api.get<FundamentalResult>(`/stock/${code}/fundamental`)
  return data
}

export interface ReportHistoryResp {
  code: string
  items: ReportHistoryItem[]
}

export async function getReportHistory(code: string, limit = 20): Promise<ReportHistoryResp> {
  const { data } = await api.get<ReportHistoryResp>(`/stock/${code}/report/history`, {
    params: { limit }
  })
  return data
}

/** SSE 生成报告: 返回取消函数。事件流: progress×N + report 终事件。 */
export function streamReport(
  code: string,
  handlers: {
    onProgress: (ev: ReportProgressEvent) => void
    onReport: (report: StockReport) => void
    onError: (message: string) => void
    onComplete?: () => void
  }
): () => void {
  const es = new EventSource(`/api/stock/${code}/report`)
  es.addEventListener('progress', (e) => {
    try {
      handlers.onProgress(JSON.parse((e as MessageEvent).data))
    } catch {
      /* 忽略坏事件 */
    }
  })
  es.addEventListener('report', (e) => {
    try {
      handlers.onReport(JSON.parse((e as MessageEvent).data))
    } catch (err) {
      handlers.onError(`报告解析失败: ${err}`)
    }
    es.close()
    handlers.onComplete?.()
  })
  es.addEventListener('error', () => {
    if (es.readyState === EventSource.CLOSED) {
      es.close()
      handlers.onComplete?.()
    } else {
      es.close()
      handlers.onError('连接中断，请重试')
      handlers.onComplete?.()
    }
  })
  return () => es.close()
}

export interface RecentReportItem extends ReportHistoryItem {
  stock_code: string
}

export async function getRecentReports(limit = 10): Promise<{ items: RecentReportItem[] }> {
  const { data } = await api.get(`/stock/report/history`, { params: { limit } })
  return data
}

// =====================================================================
// 阶段 6: 持仓管理 + 风险
// ====================================================================

import type { HoldingRow, PortfolioRisk, PortfolioSummary } from '@/types'

export interface HoldingsResp {
  holdings: HoldingRow[]
  summary: PortfolioSummary
  data_meta?: { source?: string | null; as_of?: string | null; is_stale?: boolean; warnings?: string[] }
}

export async function getHoldings(): Promise<HoldingsResp> {
  const { data } = await api.get<HoldingsResp>('/portfolio/holdings')
  return data
}

export async function addHolding(payload: {
  stock_code: string
  stock_name?: string
  quantity: number
  cost_price: number
  buy_date?: string
  notes?: string
}): Promise<HoldingRow> {
  const { data } = await api.post<HoldingRow>('/portfolio/holdings', payload)
  return data
}

export async function updateHolding(
  id: number,
  payload: { quantity?: number; cost_price?: number; buy_date?: string; notes?: string }
): Promise<HoldingRow> {
  const { data } = await api.put<HoldingRow>(`/portfolio/holdings/${id}`, payload)
  return data
}

export async function removeHolding(id: number): Promise<{ ok: boolean; removed: number }> {
  const { data } = await api.delete(`/portfolio/holdings/${id}`)
  return data
}

export async function getPortfolioRisk(): Promise<PortfolioRisk> {
  const { data } = await api.get<PortfolioRisk>('/portfolio/risk')
  return data
}

export async function getCorrelation(): Promise<PortfolioRisk['correlation']> {
  const { data } = await api.get('/portfolio/risk/correlation')
  return data as PortfolioRisk['correlation']
}

// =====================================================================
// 阶段 7: 自选股 + 大盘概览
// ====================================================================

import type {
  MarketFundFlowItem,
  MarketIndexItem,
  MarketStatistics,
  SectorItem,
  WatchlistItemView
} from '@/types'

export interface WatchlistResp {
  items: WatchlistItemView[]
  data_meta?: { source?: string | null; as_of?: string | null; warnings?: string[] }
}

export async function getWatchlist(): Promise<WatchlistResp> {
  const { data } = await api.get<WatchlistResp>('/watchlist')
  return data
}

export async function addWatchlist(code: string): Promise<WatchlistItemView> {
  const { data } = await api.post('/watchlist', { code })
  return data as WatchlistItemView
}

export async function removeWatchlist(code: string): Promise<{ ok: boolean; removed: number }> {
  const { data } = await api.delete(`/watchlist/${code}`)
  return data
}

export async function sortWatchlist(codes: string[]): Promise<{ ok: boolean }> {
  const { data } = await api.put('/watchlist/sort', { codes })
  return data
}

export async function getMarketIndices(): Promise<{ items: MarketIndexItem[] }> {
  const { data } = await api.get('/market/indices')
  return data
}

export async function getMarketSectors(): Promise<{ items: SectorItem[]; count: number }> {
  const { data } = await api.get('/market/sectors')
  return data
}

export async function getMarketFundFlow(days = 10): Promise<{ items: MarketFundFlowItem[] }> {
  const { data } = await api.get('/market/fund-flow', { params: { days } })
  return data
}

export async function getMarketStatistics(): Promise<MarketStatistics> {
  const { data } = await api.get<MarketStatistics>('/market/statistics')
  return data
}

// =====================================================================
// 阶段 8: 系统配置 / AI 持仓建议 / 数据源状态
// =====================================================================

import type {
  AppConfigResponse,
  DataSourceStatus,
  LLMTestResult,
  PortfolioAiAdvice
} from '@/types'

export async function getAppConfig(): Promise<AppConfigResponse> {
  const { data } = await api.get<AppConfigResponse>('/config')
  return data
}

export async function updateAppConfig(payload: {
  llm_provider?: string
  llm_api_key?: string
  llm_api_base?: string
  llm_model?: string
  clear_api_key?: boolean
}): Promise<AppConfigResponse> {
  const { data } = await api.put<AppConfigResponse>('/config', payload)
  return data
}

export async function testLLM(payload?: {
  provider?: string
  api_key?: string
  api_base?: string
  model?: string
}): Promise<LLMTestResult> {
  const { data } = await api.post<LLMTestResult>('/config/test-llm', payload ?? {}, {
    timeout: 60000
  })
  return data
}

export async function getDataSourceStatus(): Promise<DataSourceStatus> {
  const { data } = await api.get<DataSourceStatus>('/config/data-source-status')
  return data
}

/** AI 持仓诊断；force=true 跳过后端 10 分钟缓存重新生成 */
export async function getPortfolioAiAdvice(force = false): Promise<PortfolioAiAdvice> {
  const { data } = await api.get<PortfolioAiAdvice>('/portfolio/risk/ai-advice', {
    params: force ? { force: true } : undefined,
    timeout: 120000
  })
  return data
}

// ---------- 分钟K线数据采集 ----------

export async function startCollect(
  code: string,
  name: string,
  years = 3,
  freq = '5min'
): Promise<CollectStatus> {
  const { data } = await api.post<CollectStatus>(
    `/collect/${code}/start`,
    null,
    { params: { name, years, freq } }
  )
  return data
}

export async function getCollectStatus(code: string): Promise<CollectStatus> {
  const { data } = await api.get<CollectStatus>(`/collect/${code}/status`)
  return data
}

export async function checkCollectData(
  code: string,
  freq = '5min'
): Promise<CollectCheckResult> {
  const { data } = await api.get<CollectCheckResult>(
    `/collect/${code}/check`,
    { params: { freq } }
  )
  return data
}
