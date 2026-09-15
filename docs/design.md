# StockPanel — A股股票分析系统 设计文档

> 版本: 1.2  
> 日期: 2026-09-13  
> 状态: 阶段 1–2 已完成；双源 API 接入方案待阶段 3 实施  
> 变更: v1.2 数据源改为 Datahubco 基础版 + ProMax；保留阶段二契约，新增阶段三完成真实数据对接；配套 [implementation-plan.md](./implementation-plan.md)

---

## 1. 项目概述

### 1.1 定位

个人使用的 A 股股票分析 Web 工具，提供个股技术分析报告、持仓风险评估、自选股看板、大盘概览等功能。前后端分离架构，浏览器访问，本地运行。数据基于日频级别（Datahubco / ProMax HTTP API），不涉及实时行情和盘中交易。

### 1.2 核心价值

- **一键生成个股分析报告**：输入股票名称/代码，自动生成包含技术面、基本面、AI 情绪分析的综合报告，给出买入/持有/卖出建议
- **持仓风险透视**：手动录入持仓，系统计算 VaR、行业集中度、相关性等风险指标
- **市场全局观**：大盘概览 + 板块热度 + 自选股看板，快速掌握市场状态

### 1.3 技术约束

| 约束 | 说明 |
|------|------|
| 数据频率 | 双源 HTTP 日频数据，无实时行情 |
| 使用场景 | 个人工具，单用户，无需登录/鉴权 |
| 跨平台 | Web 应用，任何有浏览器的系统均可使用 |
| 离线能力 | 基础分析可离线运行（已缓存数据），AI 分析需联网 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────┐
│        前端 (React + Vite Dev Server)               │
│  React 18 + TypeScript + Ant Design + ECharts      │
│  开发: http://localhost:5173                        │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │
│  │ 分析报告页│ │ 持仓管理页│ │ 自选看板页│ │大盘页 │ │
│  └──────────┘ └──────────┘ └──────────┘ └───────┘ │
│  ┌──────────────────────────────────────────────┐  │
│  │          公共组件层 (K线图/指标图/搜索...)       │  │
│  └──────────────────────────────────────────────┘  │
└───────────────┬──────────────────────────────────┘
                │ HTTP (localhost:18900)
┌───────────────▼──────────────────────────────────┐
│            Python FastAPI 后端                      │
│  运行: http://localhost:18900                       │
│                                                     │
│  ┌─── API 路由层 ───────────────────────────────┐  │
│  │ /api/stock/*   个股分析                        │  │
│  │ /api/portfolio/* 持仓管理                      │  │
│  │ /api/market/*  大盘数据                        │  │
│  │ /api/watchlist/* 自选股                        │  │
│  │ /api/config/*  系统配置                        │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌─── 服务层 ───────────────────────────────────┐  │
│  │ DataFetcher    数据获取 (双源 HTTP 适配)         │  │
│  │ TechnicalEngine 技术分析引擎                   │  │
│  │ FundamentalEngine 基本面分析引擎               │  │
│  │ AIAnalyzer     AI 分析 (LLM 调用)             │  │
│  │ RiskEngine     风险评估引擎                    │  │
│  │ ReportBuilder  报告生成器                      │  │
│  │ ScoringEngine  综合评分引擎                    │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌─── 数据层 ───────────────────────────────────┐  │
│  │ SQLite (持仓/自选/配置)                        │  │
│  │ 文件缓存 (日K数据/财务数据, JSON)              │  │
│  └──────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### 2.2 启动方式

前后端分别独立启动，开发和使用方式相同：

- **后端启动**: `cd backend && uvicorn main:app --port 18900 --reload`
- **前端启动**: `cd frontend && npm run dev`（Vite 开发服务器，默认 5173 端口）
- **访问方式**: 浏览器打开 `http://localhost:5173`
- **生产部署**: `npm run build` 构建前端静态文件，由 FastAPI 直接托管（可选）

### 2.3 前后端通信

- 协议: HTTP REST API (JSON)
- 基础路径: `http://localhost:18900/api`
- 前端通过 Vite 代理转发 API 请求（开发环境），避免跨域
- 长耗时操作（如生成完整报告）: 后端使用 SSE (Server-Sent Events) 推送进度

---

## 3. 目录结构

```
stockPanel/
├── docs/                          # 文档
│   ├── design.md                  # 本设计文档
│   └── implementation-plan.md     # 实现计划
├── frontend/                      # React + Vite 前端
│   ├── package.json
│   ├── index.html                 # Vite 入口 HTML
│   ├── src/
│   │   ├── main.tsx               # React 入口
│   │   ├── App.tsx                # 根组件 + 路由
│   │   ├── pages/
│   │   │   ├── StockAnalysis/     # 股票分析报告页
│   │   │   │   ├── index.tsx      # 页面主体
│   │   │   │   ├── SearchPanel.tsx # 股票搜索面板
│   │   │   │   └── ReportView.tsx # 报告展示
│   │   │   ├── Portfolio/         # 持仓管理页
│   │   │   │   ├── index.tsx
│   │   │   │   ├── HoldingTable.tsx    # 持仓表格
│   │   │   │   └── RiskDashboard.tsx   # 风险仪表盘
│   │   │   ├── Watchlist/         # 自选股看板
│   │   │   │   └── index.tsx
│   │   │   ├── MarketOverview/    # 大盘概览
│   │   │   │   └── index.tsx
│   │   │   └── Settings/          # 设置页
│   │   │       └── index.tsx
│   │   ├── components/            # 公共组件
│   │   │   ├── KLineChart.tsx     # K线图组件 (ECharts)
│   │   │   ├── IndicatorChart.tsx # 技术指标图表
│   │   │   ├── StockSearch.tsx    # 股票搜索组件
│   │   │   ├── ScoreGauge.tsx     # 评分仪表盘
│   │   │   ├── RiskMatrix.tsx     # 风险矩阵热力图
│   │   │   └── SectorHeatmap.tsx  # 板块热力图
│   │   ├── services/
│   │   │   └── api.ts             # 后端 API 封装
│   │   ├── types/
│   │   │   └── index.ts           # 全局类型定义
│   │   └── styles/
│   │       └── global.css         # 全局样式
│   ├── tsconfig.json
│   └── vite.config.ts             # Vite 构建配置 + API 代理
├── backend/                       # Python FastAPI 后端
│   ├── requirements.txt
│   ├── main.py                    # FastAPI 入口 + CORS + 生命周期
│   ├── api/                       # 路由层
│   │   ├── __init__.py
│   │   ├── stock.py               # /api/stock/* 路由
│   │   ├── portfolio.py           # /api/portfolio/* 路由
│   │   ├── market.py              # /api/market/* 路由
│   │   ├── watchlist.py           # /api/watchlist/* 路由
│   │   └── config.py              # /api/config/* 路由
│   ├── services/                  # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── data_fetcher.py        # 统一数据入口（阶段3接入双源）
│   │   ├── providers/             # 阶段3新增：base/datahubco/promax/mock
│   │   ├── technical.py           # 技术指标计算引擎
│   │   ├── fundamental.py         # 基本面分析引擎
│   │   ├── ai_analyzer.py         # LLM AI 分析服务
│   │   ├── risk.py                # 持仓风险评估引擎
│   │   ├── scorer.py              # 综合评分引擎
│   │   └── report_builder.py      # 报告组装器
│   ├── models/                    # 数据模型
│   │   ├── __init__.py
│   │   ├── database.py            # SQLAlchemy 模型 + 初始化
│   │   └── schemas.py             # Pydantic 请求/响应模型
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py            # 应用配置 (API Key, 缓存路径等)
│   │   └── prompts/               # LLM Prompt 模板
│   │       ├── news_sentiment.txt
│   │       ├── stock_report.txt
│   │       └── portfolio_advice.txt
│   └── cache/                     # 数据缓存目录 (运行时生成)
│       ├── kline/                 # K线数据缓存
│       └── financial/             # 财务数据缓存
└── start.sh                       # 一键启动脚本 (同时启动前后端)
```

---

## 4. 模块详细设计

### 4.1 数据获取层 (DataFetcher)

> 阶段 2 已完成 17 个方法的模拟实现、文件缓存和搜索接口；阶段 3 负责接入真实双源 API，不再由用户自行补 akshare 调用。以下为兼容业务契约，双源映射及扩展规则见 §4.1.3–4.1.8。本次修订未进行网络验收。

#### 4.1.1 接口契约

DataFetcher 需要提供以下方法，返回统一的 pandas DataFrame 或 dict：

```python
class DataFetcher:
    """数据获取服务 - 统一 Datahubco / ProMax / 显式 mock 模式"""

    def get_stock_list(self) -> pd.DataFrame:
        """获取全部 A 股股票列表
        返回: code, name, industry, market(沪/深/北)
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_kline(self, code: str, period: str = "daily",
                  start_date: str = None, end_date: str = None,
                  adjust: str = "qfq") -> pd.DataFrame:
        """获取历史K线数据
        返回: date, open, close, high, low, volume, amount,
              amplitude, pct_change, change, turnover
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_stock_info(self, code: str) -> dict:
        """获取个股基本信息
        返回: {name, industry, market_cap, pe, pb, total_shares, 
               float_shares, ...}
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_financial_indicator(self, code: str) -> pd.DataFrame:
        """获取财务分析指标 (多期)
        返回: date, roe, roa, gross_margin, net_margin,
              revenue_growth, profit_growth, debt_ratio, 
              eps, bps, current_ratio, ...
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_fund_flow(self, code: str) -> pd.DataFrame:
        """获取个股资金流向
        返回: date, main_net_inflow, main_net_inflow_pct,
              super_large_net, large_net, medium_net, small_net
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_stock_news(self, code: str) -> pd.DataFrame:
        """获取个股相关新闻
        返回: title, content, pub_time, source
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_index_data(self, index_code: str = "000001",
                       period: str = "daily") -> pd.DataFrame:
        """获取指数行情 (上证/深证/创业板等)
        返回: date, open, close, high, low, volume, amount
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_industry_board_list(self) -> pd.DataFrame:
        """获取行业板块列表及涨跌幅
        返回: name, code, pct_change, turnover, 
              leading_stock, leading_pct
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_industry_board_hist(self, name: str,
                                period: str = "daily") -> pd.DataFrame:
        """获取行业板块历史行情
        返回: date, open, close, high, low, volume
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_market_fund_flow(self) -> pd.DataFrame:
        """获取大盘资金流向
        返回: date, main_net_inflow, main_net_inflow_pct, ...
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_stock_valuation(self, code: str) -> dict:
        """获取个股估值数据 (PE/PB/PS 等详细估值)
        返回: {pe_ttm, pe_static, pb, ps, pcf, 
               dividend_yield, market_cap, ...}
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_profit_sheet(self, code: str) -> pd.DataFrame:
        """获取利润表
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_balance_sheet(self, code: str) -> pd.DataFrame:
        """获取资产负债表
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_cashflow_sheet(self, code: str) -> pd.DataFrame:
        """获取现金流量表
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_holder_info(self, code: str) -> pd.DataFrame:
        """获取十大股东信息
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_dividend_history(self, code: str) -> pd.DataFrame:
        """获取分红配股历史
        数据源映射见 4.1.4；保留阶段二字段契约。
        """

    def get_industry_pe_pb(self, industry: str) -> dict:
        """获取指定行业的 PE/PB 中位数（用于估值对比）
        做法: 获取行业成份股列表 → 批量获取各股 PE/PB → 计算中位数
        返回: {pe_median, pb_median, pe_mean, pb_mean, stock_count}
        数据源映射见 4.1.4；保留阶段二字段契约。
        """
```

#### 4.1.2 缓存策略

| 数据类型 | 缓存方式 | 过期时间 |
|---------|---------|---------|
| K线日数据 | JSON 文件 (`cache/kline/{code}_{date}.json`) | 当日交易结束后更新 |
| 财务数据 | JSON 文件 (`cache/financial/{code}.json`) | 7 天 |
| 股票列表 | JSON 文件 (`cache/stock_list.json`) | 1 天 |
| 板块数据 | JSON 文件 (`cache/boards.json`) | 1 天 |
| 新闻数据 | 不缓存，每次实时获取 | - |
| 个股信息 | JSON 文件 (`cache/info/{code}.json`) | 1 天 |

以上为阶段二基线策略。阶段三按 §4.1.7 增加来源隔离、数据时间与收盘后刷新；不能将旧模拟缓存视为真实数据。


#### 4.1.3 接口依据与双源分工

依据为 [基础版调用手册](./15000积分基础功能.txt)、[ProMax 调用手册](./promax.txt) 和用户提供的两个请求示例。供应商接口名、配额、字段单位、权限、历史覆盖与最新交易日必须在阶段 3 记录真实验证证据；不以“15000 积分”“RDS 速度快”或接口数量推定可用性、吞吐量和时效。

| 项目 | Datahubco 基础版 | ProMax Relay |
|---|---|---|
| 业务基础地址 | `http://datahubco.com/app-api/openapi/v1/tushare` | `https://pcd.mobcvb.cn/tushare/pro` |
| 调用协议 | `GET /{api}`，query 参数 | `GET /{api}`，query 参数 |
| 独立鉴权 | Header `X-API-Key`，环境变量 `DATAHUBCO_API_KEY` | Header `X-API-Key`，环境变量 `PROMAX_API_KEY` |
| 优先用途 | 股票列表、日历、日线、每日指标、财务、指数等已验证基础能力 | 基础版缺口、行业/新闻/大盘资金、复权辅助及经验证的同口径备用源 |
| 响应 | `code/msg/data.fields/data.items` | 同左；另有 `ok/error/message/count/request_id` 等 |
| 能力发现 | 手册及小范围正式业务验证；未声明统一 capabilities 入口 | `/tushare/capabilities` 及 `/{api_name}`，同样需请求头鉴权 |
| 注意事项 | 区间日期成对；HTTP 不支持 `pro_bar`；网关不限流不等于上游无限制 | 无业务筛选可能自动进入探测；`__probe=1` 最多 5 行，不能用于业务验收 |

**冲突处理**：基础版 `stock-basic` 仅来自用户示例，手册为 `stock_basic`。建立规范名 `stock_basic` → 经正式验证的供应商路径映射，两种路径验证结论都写入验收记录。基础版 `adj_factor/stock_basic` 虽未在 80 接口总表逐项展开，但列在手册 §9 的已验证接口族中，仍需本项目验证。ProMax 的 `pro_bar` 是其本地聚合能力，与基础版不支持 HTTP 的说明分别处理。

`hybrid` 按下一节选择主源，备用只允许经过字段/单位/频率/复权验证的同口径接口；同一序列尽量整段切换，禁止缺一行就跨源拼一行。认证/权限/参数错误直接报告配置或能力问题，正常空结果不换源；可恢复故障才尝试有界备用或旧缓存。未验证的接口保持 unavailable。

#### 4.1.4 业务方法与接口映射

下表为待验收的路由方案。基础版不具备真实权限时必须更新该表，将通过验收的 ProMax 接口显式设为主源；不是每次请求报错后盲目尝试所有 API。

| DataFetcher 方法 | 计划主源 / 接口 | 转换与缺口处理 |
|---|---|---|
| `get_stock_list` | 基础版 `stock_basic`；ProMax 同名备用 | 沪深北分页，`ts_code/symbol/name/industry` → `code/name/industry/market`；行业按统一分类补齐 |
| `get_kline` | 基础版 `daily + daily_basic + adj_factor` | 本地复权并聚合周/月；ProMax 同名组合或 `pro_bar` 仅验证后启用 |
| `get_stock_info` | 基础版 `stock_basic + daily + daily_basic` | 基本信息、未复权收盘、同日估值拼接；各部分日期不一致需显式标注 |
| `get_financial_indicator` | 基础版 `fina_indicator` | ROE/ROA、毛利率、净利率、增长、负债率等逐字段映射；必要时用三表明确推导 |
| `get_fund_flow` | 基础版 `moneyflow` | 四类买卖额相减；主力定义为超大单与大单净额之和 |
| `get_stock_news` | ProMax `news/major_news` | 按来源与时间窗抓取后做本地个股关联，不假定接口支持 `ts_code`；无可靠关联不输出个股新闻 |
| `get_index_data` | 基础版 `index_daily/index_weekly/index_monthly` | 单独指数代码表；必要时由日线聚合，不套用股票后缀规则 |
| `get_industry_board_list` | ProMax `index_classify + index_member_all + sw_daily` | 申万 2021 一级行业；领涨股可由成分股行情派生并标注覆盖率 |
| `get_industry_board_hist` | ProMax `sw_daily` | 名称先解析唯一行业代码，周/月聚合；不得以股票指数行情冒充行业行情 |
| `get_market_fund_flow` | ProMax `moneyflow_mkt_dc` | 字段与单位先核实；缺能力时 unavailable，不用 `moneyflow_hsgt` 替代 |
| `get_stock_valuation` | 基础版 `daily_basic`，必要时三表辅助 | `pe_ttm/pe/pb/ps/dv_ttm/total_mv` 映射；PCF 仅在经营现金流 TTM 和市值口径一致时推导，否则 null |
| `get_profit_sheet` | 基础版 `income` | `end_date` → `REPORT_DATE`，营业收入/成本、营业利润、总利润、所得税、净利、归母净利映射原大写列 |
| `get_balance_sheet` | 基础版 `balancesheet` | 资产、负债、权益、货币资金、应收账款、存货、流动资产映射现有列；权益明确是否含少数股东 |
| `get_cashflow_sheet` | 基础版 `cashflow` | 经营/投资/筹资现金净额、现金净增加额映射现有大写列 |
| `get_holder_info` | ProMax `top10_holders` | 最近可见一期，保留中文目标列；持股数量转万股，按数量排名，记录报告期 |
| `get_dividend_history` | 基础版 `dividend` | 区分公告、实施、除权日期；送转与每股现金分红换算至原字段口径 |
| `get_industry_pe_pb` | ProMax 行业分类/成分 + 基础版全市场 `daily_basic` | 同分类、同交易日批量连接，分别统计有效正 PE/PB 样本中位数、均值和覆盖率 |

公共内部能力：`trade_cal` 管理交易日；`daily + stk_limit` 支持阶段 7 涨跌和涨跌停统计，按有效交易证券去重，停牌/缺行情单列。对全市场使用按交易日的分页批次，避免逐股票发出数千次查询。

项目只覆盖 A 股及分析所需指数、行业数据。分钟/实时、港美股、期货、期权、Tick 和 `p_save/p_delete` 等供应商组合写入均不属于本阶段；持仓/自选继续使用本地 SQLite。文档中明确未启用接口不进入生产依赖。

#### 4.1.5 标准化、单位与复权

1. **兼容契约**：当前 17 个公开方法继续返回 DataFrame/dict，保留已有参数与字段。一次数据任务固定 as_of（默认上海时区当前时间），通过请求级上下文或可选关键字传入，避免并发请求共享可变日期。代码以字符串保存前导零，业务层为六位股票代码，供应商层为带后缀 `ts_code`；代码表需带 `asset_type`，指数与股票不可混用。`get_kline` 继续默认 `adjust="qfq"`，明确支持 `""/"qfq"/"hfq"`；非法枚举在发请求前拒绝。`get_index_data` 可增加可选日期参数，现有调用不变。
2. **解包校验**：先检查 HTTP，再检查业务码和 `ok=false`，校验 `data.fields/items` 类型、行宽、字段重复和必需列；按字段名映射，不能靠固定下标。字段扩展可忽略，缺核心列属于协议错误。成功空数组返回带目标列的空 DataFrame；缺测不是 0。JSON 边界将 NaN/Infinity 归一化为 null。
3. **时间**：供应商日期统一传 `YYYYMMDD`，区间成对且不与 `trade_date` 混用；对外日期为 ISO 日期，新闻时间带 Asia/Shanghai 时区信息。行情按日期升序、代码/交易日去重；分页保留相同字段与筛选。未知日期或非法证券代码不向上游试错。
4. **单位表**：逐接口在验收记录中固定源单位与目标单位，以下为待核验的 Tushare 兼容预期，聚合接口不能未经核验沿用：

   | 源字段 | 项目目标 | 预期换算 |
   |---|---|---|
   | 股票 `daily.vol`（手） | `volume`（股） | ×100 |
   | 股票 `daily.amount`（千元） | `amount`（元） | ×1000 |
   | `daily_basic.total_mv/circ_mv`（万元） | 市值（亿元） | ÷10000 |
   | `daily_basic.total_share/float_share`（万股） | 股本（亿股） | ÷10000 |
   | 个股 `moneyflow.*_amount`（万元） | 资金净额（亿元） | 买卖相减后 ÷10000 |
   | 三大报表金额（元） | 原报表列（元） | 不缩放 |
   | `top10_holders.hold_amount`（股） | 持股数量（万股） | ÷10000 |
   | 百分比，如换手率、ROE、涨跌幅 | 百分数值 | 1.25 表示 1.25%，不自动 ÷100 |

   指数与申万成交量、ProMax 大盘资金、股息/送转字段需单独核验单位。指数/行业历史 `amount` 统一为元、股票历史 `volume` 为股；指数无法解释为股的量保留供应商单位并在元信息注明。行业列表的 `turnover` 表示成交额（亿元），不是 K 线 `turnover` 的换手率（%）。阶段二指数模拟金额存在亿元量级写法，迁移时同步校准 mock fixture 与单位注释。分红的目标是每 10 股：源字段经确认按每股计时，现金分红、送股、转增均乘 10，税前/税后口径显式标记。个股 `main_net_inflow_pct` 按主力净额 / 同日成交额 ×100 推导，先统一金额单位，分母缺失或为 0 则返回 null。基本估值 PE/PB 为倍数；`pe` 约定为 TTM，静态值单列。三表原大写字段与股东中文列以当前代码的完整列集为基线逐列映射，不只对齐示例列。
5. **复权**：标准路径为未复权日 OHLC + 同日有效因子。前复权 `P(t) × F(t) / F(anchor)`，anchor 为本次 as_of 及请求截止范围内最近有效交易日；后复权 `P(t) × F(t)`，具体因子基准在验收中固定。缓存记载 anchor、因子版本与 adjust；因子变化需重算受影响历史。缺因子时明确报复权不可用，不能悄悄返回未复权价格。
6. **衍生行情**：成交量/成交额保持真实未复权单位。日 K 的 change/pct_change/amplitude 按同口径相邻收盘计算，并额外请求窗口前一个有效价格；除权日展示的供应商涨跌幅与复权序列涨跌幅区分。周/月以已复权日线取首开、最高、最低、末收、量额求和，涨跌幅按上一周期末收，换手率明确为日换手率之和；不完整周期有标记。ProMax `pro_bar` 的锚点与字段需比较后才能替换此路径。
7. **现价与历史不足**：最新价、持仓金额均取未复权价格；风险收益率用同口径复权序列。停牌不伪造交易，新股不补随机历史；250 个收益率至少需要 251 个有效价格，MA250 至少 250 个点。股票与指数按共同交易日对齐，缺失比例和观察窗口随结果返回。
8. **财务时间**：按报告期、公告/实际公告日期和报表类型去重，选择 as_of 时已公开的最新版本；保留公告日期。最近 8 期不等同 8 个单季，累计转单季需按年内差分，TTM 必须补齐所需期间。负 PE、缺 PCF、缺报表字段不置零；下游按有效指标重新分配权重并标注，不足以评分则不生成基本面总分。
9. **行业与新闻**：统一行业分类源和版本；行业估值的 PE/PB 各用有效样本，目标输出保留 `stock_count` 并补充各自样本数与覆盖率，空样本返回 null。新闻关联需代码或无歧义公司名称证据，保留来源/原时间并去重；不能可靠关联时不向 AI 提供为个股新闻。

#### 4.1.6 客户端、配置与错误策略

阶段三选用同步 `httpx.Client` 以兼容现有签名和缓存装饰器，客户端连接池复用并在应用关闭时关闭。FastAPI 同步路由在线程池运行，后续 SSE 的异步流程需通过线程池调用同步数据层。

数据源配置本阶段采用 **环境变量 > 默认值**，不从 SQLite 接受密钥覆盖；现有通用配置优先级仍用于其他配置。`GET /api/config` 及新增状态接口均不能回显股票 API Key。

| 配置 | 默认/约定 |
|---|---|
| `STOCK_DATA_MODE` | `mock` 保持开发可运行；真实验收显式设置 `hybrid`，也支持单源模式 |
| `DATAHUBCO_BASE_URL` / `PROMAX_BASE_URL` | §4.1.3 两个完整业务前缀，可配置；能力目录从 ProMax 服务根地址构建 |
| `DATAHUBCO_API_KEY` / `PROMAX_API_KEY` | 无默认，只读取后端环境变量，分别绑定对应主机，不跨主机透传 |
| `DATAHUBCO_ALLOW_HTTP` | false；按手册基础版尚为 HTTP，受控网络下需显式 true 才启用；确认 HTTPS 上线后更新地址 |
| `STOCK_HTTP_CONNECT_TIMEOUT` | 5 秒 |
| `DATAHUBCO_READ_TIMEOUT` / `PROMAX_READ_TIMEOUT` | 15 / 30 秒，源于示例预算，需测量后调整 |
| `STOCK_REQUEST_DEADLINE` / `STOCK_MAX_RETRIES` | 60 秒总预算 / 最多重试 2 次；备用、排队和分页共享预算 |
| `STOCK_MAX_CONCURRENCY` / `PROMAX_REQUESTS_PER_MINUTE` | 4 / 120，保守客户端预算，不是供应商保证 |
| `STOCK_HTTP_TRUST_ENV` | true；必要时对专用股票客户端禁用环境代理，不改全进程 NO_PROXY |
| TLS | 验证开启，可配置可信 CA 文件；不用示例 verify=False 作为常规配置 |
| `STOCK_STALE_MAX_AGE` | 默认 72 小时，自 fetched_at 计；仅临时故障、同口径缓存允许，超过上限明确不可用 |

ProMax 手册声明普通业务共享 Key 2000 次/分钟、IP 200 次/分钟；探测 Key 1000、IP 60、并发 4，最多 5 行及 2 秒预算。这里只作为初始契约参考，运行中遵守响应头与 `Retry-After`，共享 IP 场景需留余量。基础版 502 可能包装上游权限或频率错误，应先解析业务信息分类。

可恢复网络失败、上游超时与暂时鉴权服务不可用采用有界退避；401/403、参数/路径/方法错误、明确未启用的 503 不重试。ProMax `minute_data_pending` 不属于本阶段业务。429 等待时间超过剩余预算时结束请求并返回可重试状态，不绕过限流并发换源。

统一 API 错误对象包含 `error/message/retryable/request_id`，脱敏后返回；用户参数错误映射 400，缺配置/能力不可用映射 503，上游协议失败映射 502，总超时映射 504，限流保留 429 及等待提示；上游鉴权失败不误报为浏览器登录失效。密钥只在 `X-API-Key` 请求头，禁止在 URL、日志、缓存、前端、验收记录中出现；禁用未经检查的跨主机重定向。

#### 4.1.7 缓存、分页与质量元信息

- 延续 JSON 文件缓存，key 包含 provider/mode/schema_version/asset_type/规范参数/fields 顺序/adjust/anchor。旧缓存无来源标记视为 mock 或旧 schema，真实模式不复用；股票列表等固定名称也必须按 provider 分目录。
- 同时保存 `source/api/as_of/fetched_at/trade_date/is_stale/adjust/anchor/coverage/missing_fields/warnings`。DataFrame 可在 `attrs["data_meta"]` 挂载，dict 使用保留键 `_data_meta`；缓存显式保存恢复该结构，禁止使用全局“最近一次来源”状态。
- 对外股票列表保持原数组，来源/时间/stale 使用响应头；新 `/info`、`/kline` 及后续报告提供 `data_meta`，路由负责将内部数据及元信息序列化，前端类型同步。`/kline` 建议响应 `{items, data_meta}`，与后续图表契约一并固定。
- 日频刷新以交易日历及该接口更新完成状态判断；行情与资金流可分别晚于收盘发布，不能午夜或 15:00 即宣称数据最新。原 24h TTL 只作兜底；周末无新交易日不反复刷新，但缓存年龄仍受过期回退上限约束。
- 分页每页 limit ≤5000 且遵循接口上限，offset 与 limit 成对。只有确认接口分页契约后才能以短页作为终止；对总量、日期覆盖和重复主键校验，识别服务端截断或忽略 offset。设置最大页数/总行数/时长保护，不支持分页时分区间；不能将不完整页集写成全量成功缓存。
- 同 key 合并并发请求；写入使用唯一临时文件和原子替换。成功空值只短缓存（建议 60 秒），异常不覆盖好缓存；旧缓存回退保留原 fetched_at 并标注过期及源失败原因。
- 核心 OHLC、复权或关键财务不足时不产生完整评级；可选新闻、资金、行业缺失返回 empty/null + 明确状态，不以随机数、中性分数或 0 填充。报表组装和 UI 必须保留部分成功信息。

#### 4.1.8 分阶段交付与验收边界

阶段 3 必须完成基础连通、17 方法契约映射、核心真实数据、缓存迁移、原搜索回归以及 `/info`、`/kline` 数据接口。新增 `GET /api/config/data-source-status` 返回配置布尔状态、已缓存能力验证结论和最近错误，不回显密钥、不触发每次全量探测。完整状态展示整合到阶段 8 设置页。

验收覆盖字段乱序、缺字段、空结果、非 JSON、业务失败码、401/403/429/503/504、重复/中断分页、单位转换、除权与停牌、新股、财报修订、同键并发、跨模式缓存及旧缓存回退。默认测试使用固定 fixture 或 httpx 模拟响应，不联网；真实 smoke 显式启用并输出脱敏记录。真实核心链路失败不能被 mock 测试成功替代。

核心能力必须真实可用；扩展能力允许有证据的 unavailable 与已验证降级，缺口需在 `docs/api-integration-validation.md` 逐项标明并带入阶段 5/7/8。详细任务及出口条件以实施计划阶段 3 为准。该验收记录、配置示例和代码均为下一阶段待交付，不代表本次已经实现。

---

### 4.2 技术分析引擎 (TechnicalEngine)

#### 4.2.1 技术指标计算

基于 K 线日数据计算以下指标（使用 pandas + numpy，如果用户安装了 TA-Lib 则优先使用）：

**趋势类指标:**

| 指标 | 参数 | 信号判断 |
|------|------|---------|
| MA (移动均线) | MA5, MA10, MA20, MA60, MA120, MA250 | 多头排列(+) / 空头排列(-) / 金叉死叉 |
| EMA (指数均线) | EMA12, EMA26 | 趋势方向和强度 |
| MACD | FAST=12, SLOW=26, SIGNAL=9 | DIF/DEA 金叉死叉, 柱状线趋势, 顶底背离 |

**震荡类指标:**

| 指标 | 参数 | 信号判断 |
|------|------|---------|
| KDJ | N=9, M1=3, M2=3 | 超买(>80) / 超卖(<20), J 值极值, 金叉死叉 |
| RSI | RSI6, RSI12, RSI24 | 超买(>70) / 超卖(<30), 背离 |
| WR (威廉指标) | N=14 | 超买(<-80) / 超卖(>-20) |

**通道类指标:**

| 指标 | 参数 | 信号判断 |
|------|------|---------|
| BOLL (布林带) | N=20, K=2 | 触及上轨/下轨, 开口/收口, 中轨趋势 |

**量价类指标:**

| 指标 | 说明 | 信号判断 |
|------|------|---------|
| 成交量MA | VOL_MA5, VOL_MA10 | 放量/缩量 |
| 量比 | 当日成交量/过去5日均量 | >2 明显放量, <0.5 明显缩量 |
| 换手率趋势 | 近期换手率变化 | 活跃度判断 |
| OBV (能量潮) | 累积量能 | 量价背离 |

**形态识别 (可选扩展):**

| 形态 | 说明 |
|------|------|
| 突破MA250 | 站上年线 |
| 均线金叉/死叉 | MA5/MA10, MA10/MA20 交叉 |
| MACD 底背离/顶背离 | 价格新低但 MACD 不创新低，反之亦然 |
| 放量突破 | 成交量放大 + 价格突破关键位 |

#### 4.2.2 技术评分模型

每个指标组输出一个 -100 到 +100 的分数，然后加权汇总：

```
技术总分 = 趋势得分 × 0.35 + 震荡得分 × 0.25 + 通道得分 × 0.15 + 量价得分 × 0.25
```

**趋势得分 (35%):**
- MA 排列: 完全多头 +80, 完全空头 -80, 混合按比例
- MACD 状态: DIF>DEA 且柱状线增长 +60, 金叉 +40, 死叉 -40, 顶背离 -60
- 价格位置: 站上 MA250 +20, 跌破 MA250 -20

**震荡得分 (25%):**
- KDJ: J<0 超卖反弹机会 +50, J>100 超买风险 -50, 金叉 +30
- RSI: RSI6<30 超卖 +40, RSI6>70 超买 -40, 背离额外 ±20
- WR: 配合验证

**通道得分 (15%):**
- BOLL: 触及下轨 +30 (超卖), 触及上轨 -30 (超买)
- 开口方向: 向上开口 +20, 向下收口 -20
- 中轨趋势: 向上 +10, 向下 -10

**量价得分 (25%):**
- 量价配合: 涨+放量 +40, 涨+缩量 -10, 跌+放量 -40, 跌+缩量 +10
- OBV 趋势: 上升 +20, 下降 -20
- 换手率异动: 异常高换手 ±20 (结合涨跌方向)

**最终技术评级:**

| 分数区间 | 技术评级 | 含义 |
|---------|---------|------|
| +60 ~ +100 | 强烈看多 | 技术面强势，多指标共振向上 |
| +20 ~ +59 | 看多 | 技术面偏强，趋势向上 |
| -19 ~ +19 | 中性 | 多空交织，方向不明 |
| -59 ~ -20 | 看空 | 技术面偏弱，趋势向下 |
| -100 ~ -60 | 强烈看空 | 技术面极弱，多指标共振向下 |

---

### 4.3 基本面分析引擎 (FundamentalEngine)

#### 4.3.1 估值分析

| 指标 | 评分逻辑 | 分值范围 |
|------|---------|---------|
| PE (TTM) | 与行业中位数对比：<0.7倍 +40, 0.7-1.0倍 +20, 1.0-1.5倍 0, >1.5倍 -20, >3倍 -40 | -40 ~ +40 |
| PB | 同上对比逻辑 | -30 ~ +30 |
| PS (市销率) | 同上对比逻辑 | -15 ~ +15 |
| 股息率 | >3% +15, 2-3% +10, 1-2% +5, <1% 0 | 0 ~ +15 |

#### 4.3.2 成长性分析

| 指标 | 评分逻辑 | 分值范围 |
|------|---------|---------|
| 营收增长率 (YoY) | >30% +30, 15-30% +20, 5-15% +10, 0-5% 0, <0% -20 | -20 ~ +30 |
| 净利润增长率 (YoY) | 同上逻辑 | -20 ~ +30 |
| ROE | >20% +30, 15-20% +20, 10-15% +10, <10% 0, <5% -10 | -10 ~ +30 |
| 连续增长季度数 | 连续 4 季 +10, 连续 2 季 +5 | 0 ~ +10 |

#### 4.3.3 财务健康度

| 指标 | 评分逻辑 | 分值范围 |
|------|---------|---------|
| 资产负债率 | <40% +20, 40-60% +10, 60-70% 0, >70% -20 | -20 ~ +20 |
| 流动比率 | >2.0 +15, 1.5-2.0 +10, 1.0-1.5 0, <1.0 -15 | -15 ~ +15 |
| 经营现金流/净利润 | >1.0 +15, 0.7-1.0 +5, <0.7 -10 (利润含金量) | -10 ~ +15 |
| 毛利率 | >50% +10, 30-50% +5, <30% 0, 下滑趋势 -10 | -10 ~ +10 |

#### 4.3.4 基本面总分

各子维度原始分求和后，按各自满分归一化到 -100 ~ +100 区间：

```
估值归一化 = 估值原始分 / 100 × 100          # 原始满分 ±100，无需缩放
成长归一化 = 成长原始分 / 100 × 100          # 原始满分 ±100，无需缩放
健康归一化 = 健康原始分 / 60 × 100           # 原始满分 ±60，缩放到 ±100

基本面总分 = 估值归一化 × 0.30 + 成长归一化 × 0.40 + 健康归一化 × 0.30
```

评级标准与技术评级相同（见 4.2.2 最终技术评级表）。

---

### 4.4 AI 分析模块 (AIAnalyzer)

#### 4.4.1 功能定位

通过 LLM 完成以下无法用规则引擎处理的分析任务：

1. **新闻情绪分析**: 批量分析个股相关新闻，判断利好/利空/中性
2. **综合报告生成**: 基于技术面+基本面数据，生成自然语言分析摘要
3. **风险提示生成**: 基于所有分析结果，总结核心风险点
4. **持仓诊断建议**: 基于持仓组合数据，给出调仓建议

#### 4.4.2 LLM 接入设计

推荐使用 Claude API（也可配置 OpenAI 等）。用户在设置页配置 API Key。

```python
class AIAnalyzer:
    """AI 分析服务"""

    def analyze_news_sentiment(self, news_list: list[dict]) -> dict:
        """分析新闻情绪
        输入: [{title, content, pub_time, source}, ...]
        输出: {
            overall_sentiment: "positive" | "negative" | "neutral",
            sentiment_score: -100 ~ +100,
            key_events: [{event, impact, sentiment}, ...],
            summary: "近期利好/利空摘要..."
        }
        """

    def generate_analysis_report(self, stock_data: dict) -> dict:
        """生成综合分析报告
        输入: {stock_info, technical_result, fundamental_result, 
               news_sentiment, kline_summary}
        输出: {
            summary: "一段话总结...",
            technical_comment: "技术面分析点评...",
            fundamental_comment: "基本面分析点评...",
            risks: ["风险1", "风险2", ...],
            catalysts: ["催化因素1", ...],
            recommendation: "买入建议原因..."
        }
        """

    def generate_portfolio_advice(self, portfolio_data: dict) -> dict:
        """持仓诊断建议
        输入: {holdings, risk_metrics, correlations, sector_exposure}
        输出: {
            overall_assessment: "总体评估...",
            risk_warnings: ["警示1", ...],
            suggestions: ["建议1", ...],
            rebalance_ideas: ["调仓思路1", ...]
        }
        """
```

#### 4.4.3 Prompt 模板管理

Prompt 模板存储在 `backend/config/prompts/` 目录下，每个分析任务一个模板文件：

- `news_sentiment.txt` — 新闻情绪分析 prompt
- `stock_report.txt` — 个股报告生成 prompt
- `portfolio_advice.txt` — 持仓建议 prompt

模板中使用 `{variable}` 占位符，运行时填充实际数据。

#### 4.4.4 API Key 配置

在设置页面提供 LLM 配置：
- API Provider 选择 (Claude / OpenAI / 自定义)
- API Key 输入
- API Base URL (可选，用于代理)
- Model 选择
- 连接测试按钮

配置存储在 SQLite 的 config 表中，API Key 加密存储。

---

### 4.5 综合评分引擎 (ScoringEngine)

#### 4.5.1 评分合成

```
综合评分 = 技术面得分 × 0.35 + 基本面得分 × 0.35 + AI情绪得分 × 0.30
```

当 AI 分析不可用时（无 API Key 或调用失败），回退为：
```
综合评分 = 技术面得分 × 0.50 + 基本面得分 × 0.50
```

#### 4.5.2 最终投资评级

| 综合评分 | 投资评级 | 建议操作 | 颜色 |
|---------|---------|---------|------|
| +60 ~ +100 | ★★★★★ 强烈推荐 | 可积极建仓 | 深红 |
| +30 ~ +59 | ★★★★ 推荐 | 可适量买入 | 红 |
| +10 ~ +29 | ★★★ 谨慎推荐 | 可少量参与 | 橙 |
| -9 ~ +9 | ★★ 中性 | 观望为主 | 灰 |
| -39 ~ -10 | ★ 不推荐 | 建议回避 | 绿 |
| -100 ~ -40 | 卖出 | 建议清仓 | 深绿 |

> **免责声明**：报告中必须显示"本分析仅供参考，不构成投资建议，投资有风险，入市需谨慎"。

---

### 4.6 股票分析报告模块 (前端)

#### 4.6.1 用户交互流程

```
用户输入股票名称/代码 → 搜索提示下拉 → 选择股票 → 点击"生成报告"
    → 显示进度条 (数据获取 → 技术分析 → 基本面分析 → AI分析 → 报告生成)
    → 展示完整报告
```

#### 4.6.2 报告页面结构

报告页面采用上下滚动的卡片式布局，包含以下区块：

**① 头部概览卡片**
- 股票名称、代码、所属行业
- 当前价格、涨跌幅 (最近交易日)
- **综合评级**（大字号突出显示，带颜色标识）
- 评分仪表盘（技术面 / 基本面 / AI情绪 三个子分数）
- 报告生成时间

**② K线图与技术指标**
- 主图: 日K线 + MA5/10/20/60 均线（支持切换日/周/月）
- 副图1: MACD 柱状图 + DIF/DEA 线
- 副图2: KDJ 曲线
- 副图3: 成交量柱状图 + 均量线
- 所有图表联动缩放，K 线图支持鼠标拖拽选择时间范围
- 在图表上标注关键信号点（金叉、死叉、突破等）

**③ 技术面分析卡片**
- 各指标组得分条形图（趋势/震荡/通道/量价）
- 每个指标的当前状态和信号（表格形式）
- 技术面总结文字（AI 生成或规则模板）

**④ 基本面分析卡片**
- 核心财务指标仪表盘（PE, PB, ROE, 营收增长等）
- 与行业均值的对比雷达图
- 最近 4 个季度的财务趋势折线图
- 基本面总结文字

**⑤ 资金面分析卡片**
- 近期资金流向柱状图（主力/散户）
- 换手率趋势
- 资金面判断

**⑥ AI 新闻情绪分析卡片**
- 情绪指标仪表盘（利好/利空/中性比例）
- 近期关键新闻列表（标题 + 情绪标签 + 日期）
- AI 情绪摘要

**⑦ 综合分析与建议卡片**
- AI 生成的综合分析段落
- 核心风险提示列表（红色警示）
- 潜在催化因素列表
- 操作建议

**⑧ 免责声明**
- 固定在底部的免责声明文字

#### 4.6.3 搜索功能设计

- 输入框支持拼音首字母、股票代码、股票名称模糊搜索
- 下拉列表显示匹配结果（代码 + 名称 + 行业）
- 股票列表数据启动时加载到前端内存（约 5000 条 A 股，数据量小）
- 搜索在前端完成，无需请求后端

---

### 4.7 持仓风险评估模块

#### 4.7.1 持仓数据管理

**数据结构:**
```
Holding:
  - stock_code: str       # 股票代码
  - stock_name: str       # 股票名称（自动填充）
  - quantity: int          # 持仓数量（股）
  - cost_price: float     # 成本价
  - buy_date: date         # 买入日期
  - notes: str             # 备注（可选）
```

**操作:**
- 添加持仓：输入代码（带搜索提示）、数量、成本价
- 编辑持仓：修改数量、成本价
- 删除持仓
- 持仓列表：表格展示全部持仓

**实时计算字段（获取最新日数据后）:**
- 当前价格、当前市值
- 浮动盈亏 = (当前价 - 成本价) × 数量
- 浮动盈亏率 = (当前价 - 成本价) / 成本价 × 100%
- 持仓占比 = 个股市值 / 总市值 × 100%
- 持有天数

#### 4.7.2 风险指标计算

**① 组合收益分析**
- 组合总收益率
- 组合年化收益率
- 基准对比（vs 沪深300）

**② VaR (Value at Risk)**
- 方法: 历史模拟法
- 使用各持仓股票过去 250 个交易日的日收益率
- 按持仓权重计算组合日收益率序列
- 计算 95% 和 99% 置信度下的日 VaR
- 输出: "在 95% 置信度下，组合单日最大可能亏损为 X 元 (Y%)"

**③ 最大回撤**
- 基于持仓建立后的组合净值曲线
- 计算最大回撤幅度和发生时间段
- 当前回撤幅度

**④ 波动率**
- 组合日收益率标准差 × √250 = 年化波动率
- 与沪深300波动率对比

**⑤ 持仓集中度**
- 前 3 大持仓占比
- HHI (赫芬达尔指数): Σ(持仓占比²)
- 集中度评级: HHI > 0.25 高集中 / 0.15-0.25 中等 / < 0.15 分散

**⑥ 行业集中度**
- 各行业持仓占比饼图
- 单一行业占比 >40% 警告
- 行业数量

**⑦ 相关性分析**
- 持仓股票间的收益率相关系数矩阵
- 热力图展示
- 高相关警告（相关系数 > 0.7 的股票对）

**⑧ Beta 系数**
- 组合相对沪深300的 Beta
- Beta > 1.2 高风险 / 0.8-1.2 中等 / < 0.8 防御型

#### 4.7.3 风险仪表盘 (前端)

页面分为两部分：

**上半部分 — 持仓表格:**
- 可编辑的持仓列表（增删改）
- 每行显示: 代码、名称、数量、成本价、现价、盈亏、盈亏率、占比
- 底部汇总行: 总市值、总盈亏、总盈亏率

**下半部分 — 风险仪表盘:**
- 风险概览卡片: VaR 数值、最大回撤、波动率、Beta、集中度评级
- 行业分布饼图
- 相关性热力图
- 组合净值曲线（vs 沪深300）
- AI 持仓诊断建议（如已配置 LLM）

---

### 4.8 自选股看板

#### 4.8.1 功能

- 添加/移除自选股（与搜索组件复用）
- 自选股列表表格: 代码、名称、最新价、涨跌幅、成交量、换手率、PE、行业
- 支持按涨跌幅/换手率/PE 排序
- 点击任意股票可快速跳转到分析报告页
- 数据来源: 每次打开看板时调用后端刷新数据

#### 4.8.2 数据存储

自选股列表存储在 SQLite `watchlist` 表:
```
watchlist:
  - id: int (主键)
  - stock_code: str
  - stock_name: str
  - added_at: datetime
  - sort_order: int
```

---

### 4.9 大盘概览

#### 4.9.1 页面内容

**① 主要指数卡片行**
- 上证指数、深证成指、创业板指、科创50
- 每个卡片: 最新点位、涨跌幅、成交额
- 迷你日K折线图（近 30 交易日）

**② 板块热度图**
- 行业板块涨跌幅热力图 (TreeMap)
- 颜色: 红涨绿跌，面积代表成交额
- 点击板块可展开查看成份股

**③ 大盘资金流向**
- 近 10 个交易日主力资金净流入柱状图
- 大单/中单/小单分布

**④ 涨跌统计**
- 上涨/下跌/平盘家数统计
- 涨停/跌停家数
- 近期趋势变化

---

## 5. 数据库设计

SQLite 数据库 `stockpanel.db`，存储在应用数据目录下。

### 5.1 表结构

**holdings (持仓表):**
```sql
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    cost_price REAL NOT NULL,
    buy_date TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**watchlist (自选股表):**
```sql
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL UNIQUE,
    stock_name TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    sort_order INTEGER DEFAULT 0
);
```

**config (配置表):**
```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**report_history (报告历史):**
```sql
CREATE TABLE report_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    rating TEXT NOT NULL,
    score REAL NOT NULL,
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## 6. API 接口设计

### 6.1 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 获取非敏感配置，不返回股票 API Key |
| GET | `/api/config/data-source-status` | 阶段 3 新增：数据源配置/能力验证状态（无密钥） |
| PUT | `/api/config` | 更新配置 |

### 6.2 股票分析接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stock/search?q={keyword}` | 搜索股票（名称/代码/拼音） |
| GET | `/api/stock/{code}/kline?period=daily&days=250&adjust=qfq` | 阶段 3：获取 K 线与 data_meta，可选成对 start_date/end_date；显式区间优先于默认 days |
| GET | `/api/stock/{code}/info` | 阶段 3：获取个股基本信息与 data_meta |
| GET | `/api/stock/{code}/technical` | 获取技术分析结果 |
| GET | `/api/stock/{code}/fundamental` | 获取基本面分析结果 |
| GET | `/api/stock/{code}/report` | 生成完整分析报告 (SSE) |
| GET | `/api/stock/{code}/report/history` | 获取历史报告列表 |

**`/api/stock/{code}/report` 响应 (SSE 流式):**

```
event: progress
data: {"stage": "fetching_data", "progress": 10, "message": "正在获取K线数据..."}

event: progress
data: {"stage": "technical_analysis", "progress": 30, "message": "正在计算技术指标..."}

event: progress
data: {"stage": "fundamental_analysis", "progress": 50, "message": "正在分析基本面..."}

event: progress
data: {"stage": "ai_analysis", "progress": 70, "message": "AI 正在分析新闻情绪..."}

event: progress
data: {"stage": "building_report", "progress": 90, "message": "正在生成报告..."}

event: report
data: { ... 完整报告 JSON ... }
```

**完整报告 JSON 结构:**

```json
{
  "stock_info": {
    "code": "600519",
    "name": "贵州茅台",
    "industry": "白酒",
    "market_cap": 20000,
    "latest_price": 1580.00,
    "pct_change": 1.25,
    "trade_date": "2026-09-11"
  },
  "rating": {
    "level": "★★★★",
    "label": "推荐",
    "score": 45.6,
    "technical_score": 38.2,
    "fundamental_score": 62.1,
    "sentiment_score": 35.0
  },
  "technical": {
    "score": 38.2,
    "trend": {"score": 42, "signals": [...]},
    "oscillator": {"score": 28, "signals": [...]},
    "channel": {"score": 35, "signals": [...]},
    "volume": {"score": 45, "signals": [...]}
  },
  "fundamental": {
    "score": 62.1,
    "valuation": {"pe": 28.5, "pb": 9.2, "score": 15, ...},
    "growth": {"revenue_growth": 12.5, "profit_growth": 15.3, "score": 55, ...},
    "health": {"debt_ratio": 25.3, "current_ratio": 3.2, "score": 70, ...}
  },
  "fund_flow": {
    "main_net_inflow_5d": -2.3,
    "trend": "outflow",
    "chart_data": [...]
  },
  "news_sentiment": {
    "overall": "positive",
    "score": 35.0,
    "key_events": [...],
    "news_list": [...]
  },
  "ai_report": {
    "summary": "...",
    "technical_comment": "...",
    "fundamental_comment": "...",
    "risks": [...],
    "catalysts": [...],
    "recommendation": "..."
  },
  "kline_data": [...],
  "indicator_data": {
    "ma": {...},
    "macd": {...},
    "kdj": {...},
    "boll": {...},
    "volume": {...}
  },
  "data_meta": {"source": "hybrid", "as_of": "2026-09-11", "is_stale": false, "warnings": []},
  "generated_at": "2026-09-12T15:30:00"
}
```

### 6.3 持仓管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/portfolio/holdings` | 获取全部持仓 (含实时计算字段) |
| POST | `/api/portfolio/holdings` | 添加持仓 |
| PUT | `/api/portfolio/holdings/{id}` | 修改持仓 |
| DELETE | `/api/portfolio/holdings/{id}` | 删除持仓 |
| GET | `/api/portfolio/risk` | 获取风险评估结果 |
| GET | `/api/portfolio/risk/correlation` | 获取相关性矩阵 |
| GET | `/api/portfolio/risk/ai-advice` | 获取 AI 持仓建议 |

### 6.4 自选股接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 获取自选股列表 (含最新行情) |
| POST | `/api/watchlist` | 添加自选股 |
| DELETE | `/api/watchlist/{code}` | 移除自选股 |
| PUT | `/api/watchlist/sort` | 调整排序 |

### 6.5 大盘数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/indices` | 主要指数数据 |
| GET | `/api/market/sectors` | 板块热度数据 |
| GET | `/api/market/fund-flow` | 大盘资金流向 |
| GET | `/api/market/statistics` | 涨跌统计 |

---

## 7. 前端技术方案

### 7.1 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18+ | UI 框架 |
| TypeScript | 5+ | 类型安全 |
| Vite | 5+ | 构建工具 + 开发服务器 |
| Ant Design | 5+ | UI 组件库 |
| ECharts | 5+ | 图表库（K线、柱状图、热力图等） |
| React Router | 6+ | 前端路由 |
| Axios | 最新 | HTTP 请求 |
| Zustand | 最新 | 轻量状态管理 |

### 7.2 页面路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 大盘概览 | 默认首页 |
| `/analysis` | 股票分析 | 搜索 + 报告展示 |
| `/analysis/:code` | 指定股票报告 | 直接打开某只股票的报告 |
| `/portfolio` | 持仓管理 | 持仓表格 + 风险仪表盘 |
| `/watchlist` | 自选股 | 自选股看板 |
| `/settings` | 设置 | API Key / 缓存 / 关于 |

### 7.3 布局

- 左侧固定侧边栏导航 (收起/展开)
- 右侧主内容区
- 整体采用暗色主题为主，支持亮/暗切换

---

## 8. 后端技术方案

### 8.1 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11+ | 运行时 |
| FastAPI | Web 框架 |
| uvicorn | ASGI 服务器 |
| Datahubco / ProMax | 双源 A 股 HTTP 数据，统一适配器 |
| pandas | 数据处理 |
| numpy | 数值计算 |
| SQLAlchemy | ORM |
| aiosqlite | 异步 SQLite |
| httpx | 股票数据同步 HTTP 客户端；LLM 可用异步客户端 |
| pydantic | 数据校验 |

可选: `TA-Lib` (如用户环境支持安装) 或 `pandas-ta` 作为备选。

### 8.2 配置管理

使用 `backend/config/settings.py` 管理配置，支持以下来源（优先级从高到低）：

1. SQLite config 表（用户在界面修改的配置）
2. 环境变量
3. 默认值

股票数据源配置独立遵循 §4.1.6 的环境变量优先规则，密钥不得由通用配置接口读取。以下为其他关键配置项:
- `LLM_PROVIDER`: claude / openai / custom
- `LLM_API_KEY`: 加密存储
- `LLM_API_BASE`: API 基础地址
- `LLM_MODEL`: 模型名称
- `CACHE_DIR`: 缓存目录路径
- `CACHE_TTL_KLINE`: K线缓存过期时间 (秒)
- `SERVER_PORT`: 后端端口号

---

## 9. 部署运行

### 9.1 开发环境

```bash
# 终端1: 启动后端
cd backend && pip install -r requirements.txt && uvicorn main:app --port 18900 --reload

# 终端2: 启动前端
cd frontend && npm install && npm run dev
```

浏览器访问 `http://localhost:5173`。

### 9.2 生产部署（可选）

前端 `npm run build` 生成静态文件到 `frontend/dist/`，FastAPI 通过 `StaticFiles` 直接托管：

```python
# backend/main.py 中添加
app.mount("/", StaticFiles(directory="../frontend/dist", html=True))
```

此模式下只需启动后端，浏览器访问 `http://localhost:18900` 即可。

### 9.3 一键启动脚本

项目根目录提供 `start.sh`（macOS/Linux）：

```bash
#!/bin/bash
cd backend && uvicorn main:app --port 18900 &
cd frontend && npm run dev &
wait
```

---

## 10. 外部服务依赖

| 服务 | 用途 | 是否必需 | 获取方式 |
|------|------|---------|---------|
| Datahubco 基础版 | 基础日频数据 | hybrid 主源 | 供应商地址 + 独立后端 Key，权限需验证 |
| ProMax Relay | 扩展能力及同口径备用 | 完整方案需要 | 供应商 HTTPS 地址 + 独立后端 Key，能力按接口验证 |
| Claude API | AI 分析 | 否（降级为纯算法） | https://console.anthropic.com — 注册获取 API Key |
| OpenAI API | AI 分析（备选） | 否 | https://platform.openai.com — 注册获取 API Key |

> 推荐使用 Claude API，模型选择 claude-sonnet-5 或 claude-haiku-4-5，性价比较高且分析能力强。

---

## 11. 非功能性要求

### 11.1 性能

下列为缓存就绪场景的目标，真实上游冷启动不视为固定 SLA。阶段 3 记录冷/热请求及批量请求数；网络等待按 §4.1.6 的单源超时和总预算处理，超过页面预算显示加载/部分结果。

- 股票搜索: 前端本地搜索，<50ms 响应
- K线数据加载: 有缓存 <200ms，无缓存 <3s
- 完整报告生成: <15s（含 AI 分析），纯算法 <5s
- 持仓风险计算: <3s（10 只股票以内）

### 11.2 错误处理

- 股票 API 调用失败: 按 §4.1.6 分类处理，临时错误有界重试/备用/旧缓存；配置、权限及协议问题明确报告，不回退模拟数据
- LLM 调用失败: 降级为纯规则分析，不阻塞报告生成
- 网络断开: 使用缓存数据，标注数据时间，提示"数据可能非最新"

### 11.3 日志

- 后端使用 Python logging，日志写入 `logs/stockpanel.log`
- 日志级别: 开发环境 DEBUG，生产环境 INFO
- 日志轮转: 单文件 10MB，保留 5 个
