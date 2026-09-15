# StockPanel — 分阶段实现计划

> 版本: 1.2  
> 日期: 2026-09-13  
> 配套文档: [design.md](./design.md)  
> 变更: v1.2 在已完成的阶段二后新增股票 API 对接阶段，原阶段 3–7 顺延为 4–8；数据源调整为 Datahubco 基础版 + ProMax

---

## 总览

本项目分为 **8 个阶段**，每个阶段结束后需通过审核检查点才可进入下一阶段。按文末依赖关系推进，进入后续阶段前必须通过其前置阶段的检查点。

```
阶段1: 项目骨架     ← 基础设施，能跑起来
阶段2: 数据层桩与缓存 ← 已完成，提供模拟数据契约
阶段3: 股票 API 对接 ← 新增，替换为可验收的真实数据
阶段4: 技术分析引擎  ← 核心算法
阶段5: 前端报告页    ← 核心功能可视化
阶段6: 持仓与风险    ← 第二大模块
阶段7: 看板与大盘    ← 辅助模块
阶段8: AI集成与打磨  ← AI + 打包发布
```

当前进度：按用户确认，阶段 1、2 已完成。**阶段 3（股票 API 对接与数据迁移）已于 2026-09-13 完成真实验收**：双源连通性探测通过（Datahubco 20/20、ProMax 能力目录 19/19 + 正式 14/15）、正式 smoke 22 verified / 1 degraded / 0 unavailable、离线契约测试 33/33、阶段 2 回归自测 49/49，勾选状态见阶段 3 任务清单，验收明细见 [api-integration-validation.md](./api-integration-validation.md)。已知缺口：ProMax major_news 上游池耗尽、news 当前 0 行（如实降级，不阻塞核心）。**阶段 4（技术分析与基本面引擎）已于 2026-09-13 完成**：TechnicalEngine（9 指标 + 5 信号 + 4 维评分，离线正确性测试 47/47）、FundamentalEngine（估值/成长/健康度按 design 4.3 满分归一）、ScoringEngine（无 AI 回退 50/50）、ReportBuilder（生成器 + SSE + report_history）、API /technical /fundamental /report(SSE) /report/history；selftest_phase4 36/36，真实数据 smoke 通过（600519：技术 -16.1 中性 / 基本面 33.9 看多 / 综合 8.9 ★★ 中性）。**阶段 5（前端报告页）已于 2026-09-13 完成**：ScoreGauge/KLineChart/IndicatorChart 三公共组件（联动缩放+暗色）、SearchPanel（最近报告）、ReportView 8 区块卡片、SSE 进度条驱动；GUI 全流程真实验证通过（搜索→进度→报告→周月切换→响应式，证据截图 gui-test-screenshots/），并修复周/月视图 MA 错位缺陷。**阶段 6（持仓管理与风险评估）已于 2026-09-13 完成**：api/portfolio.py CRUD+实时计算、RiskEngine（VaR/回撤/波动/Beta/夏普/HHI/行业/相关性/净值曲线，test_risk_engine 30/30）、selftest_phase6 33/33、前端 HoldingTable/RiskDashboard/RiskMatrix；GUI 真实验证通过（双持仓 600519+000001：VaR 1.75%、回撤 22.91%、Beta 0.11 防御型、相关性矩阵 0.41、行业双分布），并修复指数数据源误用个股 daily 的缺陷。下一步执行阶段 7（自选股看板与大盘概览）。**阶段 7（自选股看板与大盘概览）已完成**：api/watchlist.py CRUD/排序/实时行情、api/market.py 指数/板块/资金流/涨跌统计、前端 Watchlist + SectorHeatmap + MarketOverview；selftest_phase7 通过（直调端点签名与请求模型对齐后），GUI 验证通过（指数卡片迷你图、板块 TreeMap、资金流方向、涨跌统计）。**阶段 8（AI 集成与打磨）已于 2026-09-13 完成**：AIAnalyzer（claude/openai/custom 三协议 + JSON 容错 + 失败降级）、3 个 Prompt 模板、LLM 配置加密存储（Fernet + 本机 0600 密钥文件，SQLite 优先于环境变量）、配置 API（GET/PUT /api/config、POST /api/config/test-llm）、报告 AI 集成（有 Key 且调用成功 → 35/35/30；无 Key/失败/无新闻 → 50/50 并标注“AI 分析不可用”）、持仓 AI 诊断（/api/portfolio/risk/ai-advice，10 分钟结果缓存）、设置页四区块、SentimentCard/ConclusionCard AI 内容、亮暗主题切换 + 侧边栏折叠 + 统一 Loading/Error/Empty + 动态标签页标题、FastAPI 静态托管（SPA 回退）+ start.sh dev/prod/build 三模式。离线自测 selftest_phase8 120/120；回归：阶段2 49/49、阶段4 36/36、阶段6 33/33、阶段7 28/28、离线契约 33/33、技术引擎 47/47、风险引擎 30/30。端到端验证：生产模式仅后端运行于 localhost:18900 （静态资源 + SPA 回退 + API 优先级正常）；用 tests/mock_llm_server.py（OpenAI 兼容本地服务）验证 AI 全链路（情绪 +38.5/3 事件/分布、权重 35/35/30、AI 综合点评、持仓诊断、连接测试成功与失败提示）；未配置 Key 时报告正常生成并标注降级；亮/暗主题全页面正常。**遗留**：真实 Claude/OpenAI 供应商连通性未验证（本机无真实 Key；协议与降级已用 Mock 服务端到端覆盖，设置页可直接填入真实 Key 复验）；真实数据源 news 仍为 0 行，故真实模式下新闻情绪按“无可靠关联新闻”如实降级；`/analysis/:code` 前端路由暂未自动发起报告（阶段5 行为，待后续打磨）。

---

## 阶段 1: 项目骨架搭建

### 目标

搭建 Vite + React Web 前端和 Python FastAPI 后端的基础框架，验证前后端通信链路。

### 任务清单

#### 1.1 前端项目初始化

- [ ] 使用 `npm create vite@latest` 创建项目，选择 React + TypeScript 模板
- [ ] 安装依赖: `antd`, `@ant-design/icons`, `echarts`, `echarts-for-react`, `react-router-dom`, `axios`, `zustand`
- [ ] 配置 `vite.config.ts`:
  - 路径别名 (`@/` → `src/`)
  - API 代理: `/api` → `http://localhost:18900`（开发环境避免跨域）
- [ ] 创建基础布局组件:
  - 左侧侧边栏导航 (使用 Ant Design Menu)，包含: 大盘概览 / 股票分析 / 持仓管理 / 自选股 / 设置
  - 右侧主内容区 (React Router Outlet)
- [ ] 配置 React Router 路由（全部路由指向占位页面）
- [ ] 全局样式: 暗色主题基础 CSS 变量
- [ ] 创建 `src/services/api.ts`，封装 axios 实例，baseURL 指向 `/api`（通过 Vite 代理转发）

#### 1.2 后端项目初始化

- [ ] 创建 `backend/` 目录结构（按 design.md 第 3 节）
- [ ] 创建 `requirements.txt`:
  ```
  fastapi>=0.115.0
  uvicorn>=0.30.0
  sqlalchemy>=2.0.0
  aiosqlite>=0.20.0
  pydantic>=2.0.0
  pandas>=2.0.0
  numpy>=1.24.0
  httpx>=0.27.0
  ```
- [ ] 创建 `backend/main.py`:
  - FastAPI 应用实例
  - CORS 中间件（允许 localhost）
  - 生命周期事件（startup 初始化数据库，shutdown 清理）
  - `GET /api/health` 返回 `{"status": "ok", "version": "0.1.0"}`
- [ ] 创建 `backend/models/database.py`:
  - SQLAlchemy 异步引擎 + 会话工厂
  - 定义全部 4 张表的 ORM 模型（holdings, watchlist, config, report_history）
  - 自动创建表函数
- [ ] 创建 `backend/models/schemas.py`:
  - Pydantic 模型: HoldingCreate, HoldingResponse, WatchlistItem, ConfigItem 等
- [ ] 创建 `backend/config/settings.py`:
  - 配置类，包含默认值
  - 数据目录、缓存目录路径（使用系统应用数据目录）

#### 1.3 启动配置

- [ ] 创建项目根目录 `start.sh` 一键启动脚本（同时启动前后端）
- [ ] 前端启动时检测后端连通性，未连通时显示"请先启动后端"提示

### 交付物

- 前端 `npm run dev` 启动后浏览器可访问，显示侧边栏布局
- 后端 `uvicorn main:app` 启动后 `/api/health` 返回正常
- 前端可通过 Vite 代理调用后端 API
- SQLite 数据库自动创建

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 前端启动 | `npm run dev` 后浏览器访问 `localhost:5173` 正常显示页面 |
| 2 | 后端启动 | `uvicorn main:app --port 18900` 正常运行，`/api/health` 返回 200 |
| 3 | 前后端通信 | 前端页面能通过 Vite 代理调用后端并显示 health 状态 |
| 4 | 数据库 | `stockpanel.db` 自动创建，包含 4 张表 |
| 5 | 导航 | 侧边栏 5 个菜单可点击切换，路由正常 |

---

## 阶段 2: 数据获取层

### 目标

已完成 DataFetcher 桩函数、模拟数据、文件缓存和搜索链路。真实数据调用由新增阶段 3 统一接入。

### 任务清单

#### 2.1 DataFetcher 桩实现

- [x] 创建 `backend/services/data_fetcher.py`:
  - 实现 design.md 4.1.1 中定义的全部接口方法
  - 每个方法写好函数签名、参数说明、返回值结构注释
  - 方法体保留旧版 akshare TODO 并返回模拟数据（阶段 2 的历史实现；阶段 3 迁移至双 HTTP 数据源）
  - 模拟数据需覆盖各字段，方便后续模块开发和测试

- [x] 模拟数据要求:
  - `get_stock_list()`: 返回至少 20 只真实 A 股的代码和名称（硬编码）
  - `get_kline()`: 返回 250 条模拟日K数据（基于随机游走生成，价格合理）
  - `get_stock_info()`: 返回一个完整的个股信息字典
  - `get_financial_indicator()`: 返回 8 期模拟财务数据
  - `get_fund_flow()`: 返回 30 天模拟资金流向数据
  - `get_stock_news()`: 返回 10 条模拟新闻
  - `get_industry_pe_pb()`: 返回行业 PE/PB 中位数（模拟值）
  - 其他方法同理，保证返回数据结构正确

#### 2.2 缓存机制

- [x] 创建缓存装饰器 `backend/services/cache.py`:
  - `@file_cache(ttl_seconds, cache_dir)` 装饰器
  - 缓存键基于函数名 + 参数 hash
  - JSON 文件缓存，包含 `_cached_at` 时间戳字段
  - 过期检查逻辑
  - 手动清除缓存接口

- [x] 在 DataFetcher 各方法上应用缓存装饰器（按 design.md 4.1.2 的策略）

#### 2.3 股票搜索 API

- [x] 实现 `GET /api/stock/search?q={keyword}`:
  - 调用 `data_fetcher.get_stock_list()`
  - 支持按代码前缀、名称包含匹配
  - 返回匹配列表（最多 20 条）
  - 附带 `GET /api/stock/list` 全量列表接口（前端本地过滤用）
- [x] 前端搜索组件 `StockSearch.tsx`:
  - 启动时一次性加载全部股票列表到内存
  - 输入时前端本地过滤，无网络请求
  - 下拉展示: 代码 + 名称 + 行业
  - debounce 300ms

#### 2.4 缓存管理 API

- [x] `GET /api/config/cache-stats`: 返回缓存文件数量、总大小
- [x] `DELETE /api/config/cache`: 清空缓存

### 交付物

- DataFetcher 全部方法有桩实现和模拟数据
- 缓存机制可正常工作（写入/读取/过期）
- 股票搜索组件可在前端使用
- 下一阶段在保持返回契约的基础上，将桩函数迁移为 Datahubco / ProMax 适配器；模拟数据保留为显式测试模式

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 桩数据完整性 | DataFetcher 每个方法都能返回结构正确的模拟数据 |
| 2 | 缓存写入 | 首次调用后 `cache/` 目录生成对应 JSON 文件 |
| 3 | 缓存读取 | 二次调用不触发数据生成，直接读缓存 |
| 4 | 缓存过期 | 修改缓存文件时间戳后，重新调用会刷新数据 |
| 5 | 搜索功能 | 前端搜索框输入"贵州"或"600"能显示匹配结果 |
| 6 | API 契约 | 每个 DataFetcher 方法的返回字段与 design.md 一致 |

---

## 阶段 3: 股票 API 对接与数据迁移（新增）

### 目标与边界

将阶段二的 17 个 DataFetcher 方法接入 Datahubco 基础版与 ProMax，交付可供分析引擎、持仓、自选和大盘模块使用的日频真实数据。基础版优先承载已验证的基础数据；ProMax 补齐复权、新闻、行业等能力。具体方法路由以 [design.md §4.1.3–4.1.8](./design.md#413-接口依据与双源分工) 为准。

前置：阶段 2 的契约与搜索自测通过。此阶段不实现评分、报告页面、分钟行情、交易功能或供应商云端组合管理；不要求遍历接入手册全部接口。

### 任务清单

#### 3.1 契约核对与最小真实连通性验证

- [x] 阅读 `docs/15000积分基础功能.txt`、`docs/promax.txt` 和用户的两个调用示例，建立逐方法接口清单。
- [x] 新建 `docs/api-integration-validation.md`，记录接口、请求方法、脱敏参数、HTTP/业务码、字段、行数、数据时间、响应头、耗时、分页行为、可用权限及结论；区分“文档声明 / 探测通过 / 正式请求通过 / 不支持”。不保存密钥。
- [x] 基础版核对 `stock-basic`（用户示例）与 `stock_basic`（手册）实际路由，固定验证成功的显式别名，不进行全局连字符替换；连通性请求使用 `limit=3`，完整股票列表另做分页验收。（两别名返回逐字段一致，固定规范名 stock_basic）
- [x] ProMax 读取 `/tushare/capabilities` 及所需接口的单项能力，检查 `enabled/required/required_any/methods`；目录不位于 `/tushare/pro` 下。（19/19 通过）
- [x] `__probe=1` 仅用于存在性诊断；正式查询提供代码、交易日、日期区间或 `list_status` 等业务筛选。确实无筛选的接口显式 `__probe=0`；`limit/fields` 不视为业务筛选。
- [x] 用 `000001.SZ`、`600519.SH`、一只股票列表验证存在的北交所股票，以及 `000300.SH` 做小范围真实请求；日期取交易日历内已完成交易日，不把用户示例日期固定为生产默认值。
- [x] 记录基础版 HTTP 传输条件、ProMax TLS/代理兼容性；按设计的配置策略处理，不复制全局 `NO_PROXY='*'` 或 `verify=False` 为默认行为。（明文 HTTP 需 DATAHUBCO_ALLOW_HTTP 显式开关；ProMax 默认校验证书）

#### 3.2 客户端、配置与数据源路由

- [x] 在 `backend/services/providers/` 建立 `base.py`、`datahubco.py`、`promax.py`、`mock.py`，在 `data_fetcher.py` 保留统一入口；请求解析、参数规范化、字段映射独立为可测试模块。（base.py 拆为 baseclient.py + errors.py + normalize.py）
- [x] 使用复用连接的同步 `httpx.Client`，保持当前 DataFetcher 同步签名；同步 FastAPI 路由走线程池，未来 async/SSE 调用通过线程池桥接，避免阻塞事件循环；应用关闭时释放客户端。
- [x] `backend/config/settings.py` 增加双端地址与独立环境变量密钥、模式、主备路由、超时、限流、重试、TLS、代理及过期缓存开关；补充 `.env.example`（仅占位值）及实际加载方式，确认 `.gitignore` 覆盖本地密钥文件。
- [x] 模式明确为 `mock / datahubco / promax / hybrid`；hybrid 按接口路由，不能把任意错误统一转发到另一端。数据源配置初始化后生效，更改环境变量需重启；此阶段不引入在线密钥编辑。
- [x] 建立统一错误类型及后端错误响应：鉴权、参数、权限、限流、暂时故障、未启用、协议错误、正常空结果；记录脱敏请求 ID。
- [x] 不再依赖用户自行补 akshare TODO；清查 import 后移除未使用的 akshare 依赖。mock 仅显式启用，real 模式缺密钥报配置错误。

#### 3.3 股票列表、日历、行情与复权（核心必需）

- [x] 完整股票列表按沪、深、北覆盖并去重，保留 `code/name/industry/market`；历史持仓中的退市证券保留可识别性。建立带资产类型的代码映射，解决 `000001.SZ` 股票与 `000001.SH` 指数冲突。（5562 只，北交所 343）
- [x] 实现交易日历和最近已完成且上游已更新交易日查询；停牌、周末、节假日、新股历史不足返回实际覆盖信息。（as_of 取最近已发布交易日，行情/资金流收口时间区分）
- [x] 对接 `daily/daily_basic/adj_factor`；按统一日期、代码合并，补齐现有 K 线契约的 12 列，处理字段乱序、缺失、非数值和单位转换。
- [x] 实现不复权、前复权、后复权及一致的日/周/月聚合；不得调用基础版 HTTP `pro_bar`。ProMax `pro_bar` 先验证能力、字段和复权锚点，再允许作为对照或同口径备用路径。（本地 qfq vs pro_bar 复算偏差 0.0000%）
- [x] `get_stock_info/get_stock_valuation` 使用未复权最近收盘价、同日估值数据；PE/PB/市值/股本单位有固定映射，不能用复权价计算持仓市值。
- [x] 指数对接日/周/月与沪深 300 基准；保留当前 `get_index_data` 调用兼容，增加可选日期范围，以满足风险窗口。
- [x] 历史请求按交易日数量补足：MA250 需至少 250 个有效收盘价，250 个收益率需至少 251 个价格点；不足时输出缺口，不生成补位价格。（kline 请求按交易日数×1.55 自然日取窗，coverage 如实标注）

#### 3.4 财务、行业、资金与新闻（完整契约）

- [x] 按 design.md 映射表覆盖全部 17 个方法，逐字段固定源字段、目标字段、单位、空值、推导公式和业务口径。
- [x] 对接 `fina_indicator/income/balancesheet/cashflow`，保留现有大写报表字段；按公告时间与报告期选择可见版本，区分累计、单季和 TTM，最近 8 期不足时保留实际期数。（新增 ANN_DATE/F_ANN_DATE 修订可见性列）
- [x] 接入股东、分红；确认股数和每股分红单位、公告日/除权日含义，未实施方案不能当已实施分红。（仅 div_proc=实施；每股→每10股×10）
- [x] 接入 `moneyflow` 与 ProMax 大盘资金流，定义超大/大/中/小单与主力净额口径；不把北向净流入当大盘主力净流入。（主力=超大+大净额；区间优先单请求）
- [x] 统一采用申万 2021 一级行业，建立分类、成分、名称与代码映射，支持行业列表、历史、行业 PE/PB 中位数及样本覆盖率；不能混用另一分类的名称直接关联。（31 行业 verified，含覆盖率字段）
- [x] 接入 ProMax 新闻，显式指定来源和窗口，在本地进行股票关联、去重、时间标准化；市场新闻不直接全部贴为个股新闻，无可靠关联返回空并标注原因。（news 200 但当前 0 行、major_news 上游池耗尽——smoke 记 degraded，不用 mock 顶替）
- [x] 为阶段 7 的涨跌统计准备全市场 `daily + stk_limit` 数据能力，可新增内部 helper；按涨跌停价格比较，不硬编码统一 10% 阈值。（daily_with_limits helper 已预留并验证）
- [x] 每个非核心方法必须得到“真实数据已验证”或“明确不可用并验证降级”的结论；缺失 PCF 等字段为 null，空数据不伪造成 0。（22 verified / 1 degraded / 0 unavailable）

#### 3.5 分页、限流、缓存和数据质量

- [x] 固定筛选及字段顺序分页，limit 不超过 5000 且服从单接口限制；针对服务端较小截断、重复页、不支持 offset 和请求上限做检测，必要时分日期窗口；失败页面不形成完整缓存。（fetch_all：短页终止/重复页检测/413 自适应减页/350 天切窗）
- [x] ProMax 普通业务按手册的 Key/IP 双重配额建立队列，配置保守预算（初始最多 120 次/分钟、4 并发），根据响应头调整；探测单独限制。基础版也需限制并发，不能将“无网关限流”当上游无限制。
- [x] 429 尊重 `Retry-After`；暂时网络/502/504 等最多重试 2 次并指数退避加抖动；解析 502 的上游权限错误避免盲重试；401/403/400/404/405 与明确未启用 503 不循环重试。总请求链设置 60 秒预算（包含排队、分页/切窗、重试及备用源），超时明确报告未完成覆盖，长历史任务另行分批执行。
- [x] 缓存增加 provider、模式、schema 版本、资产类型、周期、复权方式及锚点；固定名称股票列表缓存同样分源。阶段二无来源标记缓存禁止进入真实模式。
- [x] 交易日收盘与上游发布时间驱动刷新，行情和资金流分别判断更新就绪；财务保留 7 天上限并支持公告触发刷新，新闻维持按请求获取。（行情 17 点、资金流 19:30 收口）
- [x] 缓存元信息与 DataFrame/dict 数据一起序列化，保留数据截止日、来源、覆盖率、过期状态；并发请求合并、唯一临时文件原子写入，缓存失败不破坏上次有效结果。
- [x] 正常空结果短缓存；失败不覆盖有效缓存。仅在可恢复故障时按配置使用有限龄的同口径旧缓存，标注 stale；不以正常空数据触发换源，不默默改为 mock。

#### 3.6 API 联调、回归与切换

- [x] 保留 `/api/stock/search`、`/api/stock/list` 原列表响应及前端搜索契约；补充响应头数据来源/日期/过期状态，元信息在成功及缓存路径一致。
- [x] 将原分析阶段的 `GET /api/stock/{code}/info`、`GET /api/stock/{code}/kline` 前移到本阶段；保留默认 250 天、period 参数，增加并校验 adjust/日期参数；不得影响静态 `/search`、`/list` 路由匹配。
- [x] 新增只读 `GET /api/config/data-source-status`，只展示模式、密钥是否配置、最近验证结论、接口能力与错误类别，不回传密钥，不在每次读取时探测全接口；`/api/health` 保留进程健康语义。
- [x] 更新 Pydantic/TypeScript 契约及必要的搜索错误/过期提示，完整设置页在阶段 8 整合此状态接口。（DataMeta/KlineResponse/StockInfoResponse；前端 TS 契约随阶段 5 前端联调同步）
- [x] 将阶段二自测显式锁定 mock，新增 httpx 模拟响应的契约测试和手动 opt-in 的真实 smoke 脚本；默认测试不联网、不依赖私密 Key。（33/33 + 49/49 + smoke opt-in）
- [x] 更新 `docs/startup.md` 的配置与验证步骤，提交脱敏验收记录；先独立真实缓存冷启动，再检查热缓存和断网降级，重启切换 mock/real 验证无串数据。（冷/热耗时与请求数记录于验收文档 §7）
- [x] 回退用显式模式切换并重启，保留 SQLite 持仓/自选数据；真实业务出错时不自动进入演示模式。

### 交付物

双源客户端与适配器、17 方法映射、配置示例、核心数据 API、数据源状态接口、升级后的缓存、离线契约测试、真实 smoke 脚本、脱敏验收记录及启动说明。以上均为本阶段待实现交付物。

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 双端真实连通 | 分别记录 HTTP 与业务成功码、真实业务条件及数据时间；stock-basic 别名确认；探测结果单列 |
| 2 | 列表完整性 | 沪深北分市场分页，代码唯一；页上限/重复页可检测，不以 3/5 行样本当全量 |
| 3 | 核心数据 | 列表、日历、日线/复权、个股资料/估值、财务指标及三表、基准指数真实可用；缺权限不得勾选完成 |
| 4 | 兼容契约 | 17 方法逐项记录字段/类型/单位；现有搜索前端无需改变选择语义，旧报表列名保留 |
| 5 | 复权与金额 | 含除权样本的三种复权可复算，周/月聚合一致；100 手、1000 千元等单位用固定样本核验，未复权价用于市值 |
| 6 | 财务正确性 | 同期修订与公告时间选择可复现，累计/单季/TTM 不混用，未公告数据不可见 |
| 7 | 数据不足 | 节假日、停牌、新股、空结果、缺字段均有明确信息；不足 251 个收盘价不能伪装满足 250 日风险窗口 |
| 8 | 可靠性 | 429、权限错误、非 JSON、超时、未启用 503、分页中断有测试；重试及总耗时有上限 |
| 9 | 缓存迁移 | mock/双源/复权隔离；热缓存字段及元信息无丢失，并发写入及 stale 回退不污染有效缓存 |
| 10 | 扩展能力 | 行业、资金、新闻、股东、分红每项真实验证或显式 unavailable；相应后续功能保留缺口，不宣称全量可用 |
| 11 | 密钥与传输 | 密钥只在后端请求头，日志/缓存/响应/前端/示例不泄漏；TLS 默认校验，基础版明文配置有显式开关 |
| 12 | 回归与性能 | 阶段二离线自测通过；记录冷/热缓存耗时及上游请求数，10 只持仓场景复用批次、不重复拉全市场 |

**阶段出口**：1–9、11–12 必须通过；第 10 项允许供应商缺能力时以“降级通过”记录具体受影响功能。核心数据不可用则阶段 3 不能完成；扩展能力缺口进入阶段 5/7/8 对应待办，后续功能不能以 mock 通过真实验收。

---

## 阶段 4: 技术分析与基本面引擎

### 目标

实现技术指标计算、基本面评分、综合评分引擎。这是系统的核心算法层。

### 任务清单

#### 4.1 技术分析引擎

- [x] 创建 `backend/services/technical.py` — `TechnicalEngine` 类:

  **指标计算方法** (全部基于 pandas/numpy 实现):
  - [x] `calc_ma(df, periods=[5,10,20,60,120,250])` → 各周期均线
  - [x] `calc_ema(df, periods=[12,26])` → 指数均线
  - [x] `calc_macd(df, fast=12, slow=26, signal=9)` → DIF, DEA, MACD柱
  - [x] `calc_kdj(df, n=9, m1=3, m2=3)` → K, D, J 值
  - [x] `calc_rsi(df, periods=[6,12,24])` → RSI 值
  - [x] `calc_boll(df, n=20, k=2)` → 上轨, 中轨, 下轨
  - [x] `calc_wr(df, n=14)` → 威廉指标
  - [x] `calc_obv(df)` → OBV 能量潮
  - [x] `calc_volume_ma(df, periods=[5,10])` → 成交量均线

  **信号判断方法**:
  - [x] `detect_ma_alignment(ma_data)` → 多头/空头/混合排列
  - [x] `detect_cross(fast, slow)` → 金叉/死叉 + 发生时间
  - [x] `detect_divergence(price, indicator)` → 顶背离/底背离
  - [x] `detect_overbought_oversold(indicator, upper, lower)` → 超买/超卖
  - [x] `detect_volume_price(kline, vol_ma)` → 量价关系判断

  **评分方法** (按 design.md 4.2.2):
  - [x] `score_trend(kline, indicators)` → -100 ~ +100
  - [x] `score_oscillator(indicators)` → -100 ~ +100
  - [x] `score_channel(kline, boll)` → -100 ~ +100
  - [x] `score_volume(kline, indicators)` → -100 ~ +100
  - [x] `get_technical_score(kline)` → 加权总分 + 评级 + 全部子项明细

#### 4.2 基本面分析引擎

- [x] 创建 `backend/services/fundamental.py` — `FundamentalEngine` 类:

  **评分方法** (按 design.md 4.3):
  - [x] `score_valuation(stock_info, financial_data)` → 估值得分
  - [x] `score_growth(financial_data)` → 成长性得分
  - [x] `score_health(financial_data)` → 财务健康度得分
  - [x] `get_fundamental_score(stock_info, financial_data)` → 加权总分 + 评级 + 全部子项

#### 4.3 综合评分引擎

- [x] 创建 `backend/services/scorer.py` — `ScoringEngine` 类:
  - [x] `calculate_rating(tech_score, fund_score, sentiment_score=None)`:
    - 有 AI 分数: 35/35/30 加权
    - 无 AI 分数: 50/50 加权
    - 返回: 综合分数 + 星级评级 + 评级标签 + 建议操作

#### 4.4 报告组装器

- [x] 创建 `backend/services/report_builder.py` — `ReportBuilder` 类:
  - [x] `build_report(code)` 方法:
    1. 调用阶段 3 的 DataFetcher 获取原始数据，透传来源/数据日期/缺失和 stale 元信息；核心数据不足时不产出完整评级，可选指标缺失不按 0 评分
    2. 调用 TechnicalEngine 计算技术分析
    3. 调用 FundamentalEngine 计算基本面分析
    4. 调用 ScoringEngine 计算综合评分
    5. 组装成 design.md 6.2 中定义的完整报告 JSON
    6. 存储到 report_history 表
  - [x] 使用生成器 yield 进度事件，支持 SSE 推送

#### 4.5 API 路由

- [x] 实现 `backend/api/stock.py` 中的接口:
  - [x] `GET /api/stock/{code}/technical` — 返回技术分析结果
  - [x] `GET /api/stock/{code}/fundamental` — 返回基本面分析结果
  - [x] `GET /api/stock/{code}/report` — SSE 流式返回完整报告
  - 复用阶段 3 已交付的 `/info`、`/kline` 原始数据接口，不重复实现

### 交付物

- 全部技术指标可正确计算
- 评分模型产出合理的分数和评级
- `/api/stock/{code}/report` 能返回完整的报告 JSON
- SSE 进度推送正常

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 指标计算 | 用已知数据验证 MA/MACD/KDJ/RSI/BOLL 计算结果正确 |
| 2 | 信号检测 | 金叉/死叉/超买/超卖 判断逻辑正确 |
| 3 | 技术评分 | 模拟上涨趋势股票得到正分，下跌趋势得到负分 |
| 4 | 基本面评分 | 高 ROE 低 PE 股票得到正分，反之负分 |
| 5 | 综合评分 | 评级映射正确（分数 → 星级 → 标签） |
| 6 | 报告完整性 | `/api/stock/600519/report` 返回的 JSON 包含 design.md 定义的全部字段 |
| 7 | SSE | 前端能通过 EventSource 接收进度事件 |
| 8 | 降级逻辑 | 无 AI 时评分权重自动调整为 50/50 |

---

## 阶段 5: 股票分析报告前端页面

### 目标

实现股票分析报告的完整前端页面，包括搜索、K线图、指标图、报告展示。

### 任务清单

#### 5.1 公共图表组件

- [x] `KLineChart.tsx` — K线图组件:
  - 基于 ECharts 实现日K线图
  - 主图: 蜡烛图 + MA 均线叠加（可勾选显示/隐藏各均线）
  - 支持鼠标拖拽缩放、十字光标、tooltip 显示 OHLCV
  - 支持切换日/周/月K
  - 在图上标注关键信号点（金叉、死叉等，标注数据来自后端）

- [x] `IndicatorChart.tsx` — 技术指标副图组件:
  - 通用副图容器，接收指标类型参数
  - MACD 模式: DIF/DEA 线 + 柱状图（红绿色区分）
  - KDJ 模式: K/D/J 三线 + 超买超卖区域标注
  - 成交量模式: 柱状图（涨红跌绿）+ 均量线
  - 与主图联动: 缩放同步、时间轴同步

- [x] `ScoreGauge.tsx` — 评分仪表盘组件:
  - 半圆仪表盘，-100 到 +100
  - 颜色渐变: 深绿 → 绿 → 灰 → 红 → 深红
  - 居中显示分数和评级文字
  - 支持小尺寸模式（子分数展示用）

#### 5.2 股票分析页面

- [x] `pages/StockAnalysis/index.tsx` — 页面主体:
  - 顶部搜索区域 (复用 StockSearch 组件)
  - 搜索结果选择后触发报告生成
  - 生成期间显示进度条 (接收 SSE 事件)
  - 生成完成后渲染 ReportView

- [x] `pages/StockAnalysis/SearchPanel.tsx`:
  - 居中大搜索框（无报告时显示）
  - 最近搜索记录（从 report_history 获取）
  - 搜索后缩小到顶部

- [x] `pages/StockAnalysis/ReportView.tsx` — 报告展示:
  - 按 design.md 4.6.2 的 8 个区块实现卡片式布局
  - 每个区块为一个独立子组件:

  **① HeaderCard** — 头部概览:
  - [x] 股票名称 + 代码 + 行业标签
  - [x] 当前价格 + 涨跌幅（红涨绿跌）
  - [x] 综合评级大字显示 + 颜色
  - [x] 三个小型 ScoreGauge（技术/基本面/AI情绪）
  - [x] 报告时间

  **② ChartSection** — K线与指标图:
  - [x] KLineChart 主图
  - [x] 3 个 IndicatorChart 副图 (MACD / KDJ / 成交量)
  - [x] 日/周/月切换按钮
  - [x] 图表联动缩放

  **③ TechnicalCard** — 技术面分析:
  - [x] 4 个子维度评分条形图（趋势/震荡/通道/量价）
  - [x] 指标信号表格（指标名 / 当前值 / 信号 / 方向箭头）
  - [x] 技术面文字总结

  **④ FundamentalCard** — 基本面分析:
  - [x] 核心指标卡片行 (PE / PB / ROE / 营收增长 / 利润增长)
  - [x] 行业对比雷达图 (ECharts radar)
  - [x] 最近 4 季度趋势折线图
  - [x] 基本面文字总结

  **⑤ FundFlowCard** — 资金面:
  - [x] 近期资金流向柱状图
  - [x] 换手率趋势线
  - [x] 资金面判断文字

  **⑥ SentimentCard** — AI 新闻情绪（预留，阶段8实现内容填充）:
  - [x] 情绪分布饼图占位
  - [x] 新闻列表占位
  - [x] 无 AI Key 时显示"未配置 AI 分析"提示

  **⑦ ConclusionCard** — 综合分析（预留，阶段8实现 AI 内容填充）:
  - [x] 纯规则生成的简要结论
  - [x] 风险提示列表
  - [x] 操作建议

  **⑧ Disclaimer** — 免责声明:
  - [x] 固定文字

### 交付物

- 完整可交互的股票分析报告页面
- 搜索 → 进度条 → 报告展示 全流程可用
- K线图可拖拽缩放、指标副图联动
- 真实数据全流程展示通过；模拟数据仅用于显式演示，缺失/过期数据有清楚提示

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 搜索流程 | 输入关键词 → 下拉选择 → 生成报告 全流程顺畅 |
| 2 | 进度条 | SSE 进度事件驱动进度条从 0 到 100，阶段文字正确更新 |
| 3 | K线图 | 蜡烛图渲染正确，均线叠加，可拖拽缩放 |
| 4 | 指标图 | MACD/KDJ/成交量副图渲染正确，与主图联动 |
| 5 | 评分展示 | 仪表盘显示分数和评级，颜色与分数匹配 |
| 6 | 报告卡片 | 8 个区块全部渲染，无空白或报错 |
| 7 | 响应式 | 浏览器窗口调整大小后图表自动适配，不出现截断 |
| 8 | 暗色主题 | 所有组件在暗色主题下可读性良好 |

---

## 阶段 6: 持仓管理与风险评估

### 目标

实现持仓的 CRUD 管理和完整的风险评估计算引擎及前端展示。

### 任务清单

#### 6.1 持仓管理后端

- [x] 实现 `backend/api/portfolio.py` 全部 CRUD 路由:
  - [x] `GET /api/portfolio/holdings` — 返回持仓列表 + 实时计算字段（现价、盈亏、占比等）
  - [x] `POST /api/portfolio/holdings` — 添加持仓（校验代码有效性）
  - [x] `PUT /api/portfolio/holdings/{id}` — 修改持仓
  - [x] `DELETE /api/portfolio/holdings/{id}` — 删除持仓

- [x] 持仓实时计算逻辑:
  - 获取各持仓股票的最新日数据（通过 DataFetcher）
  - 计算: 当前市值、浮动盈亏、盈亏率、持仓占比、持有天数
  - 汇总: 总市值、总盈亏、总盈亏率

#### 6.2 风险评估引擎

- [x] 创建 `backend/services/risk.py` — `RiskEngine` 类:

  **基础数据准备**:
  - [x] `_get_portfolio_returns(holdings)`: 获取各持仓股票过去 250 天日收益率，按权重合成组合收益率序列

  **风险指标计算** (按 design.md 4.7.2):
  - [x] `calc_var(returns, confidence=0.95)` → VaR 值 + 金额
  - [x] `calc_max_drawdown(returns)` → 最大回撤幅度 + 起止时间
  - [x] `calc_volatility(returns)` → 年化波动率
  - [x] `calc_beta(portfolio_returns, index_returns)` → Beta 系数
  - [x] `calc_sharpe(returns, risk_free_rate=0.02)` → 夏普比率
  - [x] `calc_concentration(holdings)` → HHI指数 + 前3大占比 + 评级
  - [x] `calc_sector_exposure(holdings)` → 行业分布字典
  - [x] `calc_correlation_matrix(holdings)` → 持仓股票间相关系数矩阵
  - [x] `calc_portfolio_curve(holdings)` → 组合净值曲线（vs 沪深300）

  **汇总**:
  - [x] `get_risk_assessment(holdings)` → 全部风险指标 + 风险等级

- [x] 实现风险 API 路由:
  - [x] `GET /api/portfolio/risk` — 返回全部风险指标
  - [x] `GET /api/portfolio/risk/correlation` — 返回相关性矩阵

#### 6.3 持仓管理前端

- [x] `pages/Portfolio/index.tsx` — 页面主体:
  - 上半部分: 持仓表格
  - 下半部分: 风险仪表盘
  - 无持仓时显示引导添加

- [x] `pages/Portfolio/HoldingTable.tsx`:
  - [x] Ant Design Table 可编辑表格
  - [x] 列: 代码、名称、数量、成本价、现价、盈亏、盈亏率、占比
  - [x] 盈亏列红涨绿跌
  - [x] 添加按钮 → 弹窗（StockSearch + 数量 + 成本价 + 买入日期）
  - [x] 行内编辑数量和成本价
  - [x] 删除确认
  - [x] 底部汇总行

- [x] `pages/Portfolio/RiskDashboard.tsx`:
  - [x] 风险概览卡片行: VaR / 最大回撤 / 波动率 / Beta / 夏普 / 集中度
  - [x] 每个卡片: 数值 + 评级颜色 + 小字说明
  - [x] 行业分布饼图 (ECharts pie)
  - [x] 相关性热力图 (ECharts heatmap) — `RiskMatrix.tsx`
  - [x] 组合净值曲线 vs 沪深300 对比折线图
  - [x] 持仓不足 2 只时隐藏相关性分析

### 交付物

- 持仓可增删改查，数据持久化到 SQLite
- 风险指标全部可计算并展示
- 相关性热力图、行业饼图、净值曲线正常渲染

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | CRUD | 添加、编辑、删除持仓操作正常，刷新后数据保持 |
| 2 | 实时计算 | 持仓表格中现价、盈亏、占比等字段正确 |
| 3 | VaR | VaR 计算结果在合理范围内（单日 1-5% 级别） |
| 4 | 最大回撤 | 回撤计算正确，起止时间合理 |
| 5 | 相关性 | 相关系数矩阵对角线为 1，其他值在 -1~1 之间 |
| 6 | 集中度 | HHI 计算正确，评级映射正确 |
| 7 | 净值曲线 | 组合净值与沪深300对比图正常显示 |
| 8 | 空状态 | 无持仓时显示引导，有 1 只时隐藏相关性分析 |

---

## 阶段 7: 自选股看板与大盘概览

### 目标

实现自选股管理看板和大盘概览页面。

### 任务清单

#### 7.1 自选股后端

- [x] 实现 `backend/api/watchlist.py`:
  - [x] `GET /api/watchlist` — 返回自选列表 + 各股最新行情数据
  - [x] `POST /api/watchlist` — 添加自选（去重）
  - [x] `DELETE /api/watchlist/{code}` — 移除自选
  - [x] `PUT /api/watchlist/sort` — 调整排序

#### 7.2 自选股前端

- [x] `pages/Watchlist/index.tsx`:
  - [x] 顶部: 搜索添加自选股按钮
  - [x] Ant Design Table 展示:
    - 列: 代码、名称、最新价、涨跌幅、成交量(万手)、换手率、PE、行业
    - 涨跌幅红涨绿跌
    - 支持按任意列排序
    - 右键/操作列: 移除自选、生成报告（跳转分析页）
  - [x] 空状态引导
  - [x] 拖拽排序（可选）

#### 7.3 大盘数据后端

- [x] 实现 `backend/api/market.py`:
  - [x] `GET /api/market/indices` — 返回主要指数数据（上证/深证/创业板/科创50）+ 近 30 日K线迷你数据
  - [x] `GET /api/market/sectors` — 返回行业板块涨跌排名 + 成交额（用于热力图）
  - [x] `GET /api/market/fund-flow` — 返回近 10 日大盘资金流向
  - [x] `GET /api/market/statistics` — 返回涨跌家数统计

#### 7.4 大盘概览前端

- [x] `pages/MarketOverview/index.tsx`:

  **① 指数卡片行**:
  - [x] 4 个指数卡片 (上证/深证/创业板/科创50)
  - [x] 每卡片: 名称、点位、涨跌幅、成交额
  - [x] 迷你面积图（近 30 日走势，ECharts 迷你图）
  - [x] 涨红跌绿背景色

  **② 板块热力图**:
  - [x] `SectorHeatmap.tsx` 组件
  - [x] ECharts TreeMap 实现
  - [x] 颜色: 涨幅越大越红，跌幅越大越绿
  - [x] 面积: 代表成交额大小
  - [x] tooltip 显示详细数据
  - [x] 可点击（预留跳转行业详情的能力）

  **③ 资金流向**:
  - [x] 近 10 日主力资金净流入柱状图
  - [x] 红色正流入，绿色净流出

  **④ 涨跌统计**:
  - [x] 上涨/下跌/平盘家数 — 横向堆叠柱状图或数字卡片
  - [x] 涨停/跌停家数高亮显示

### 交付物

- 自选股看板可增删查看，数据实时刷新
- 大盘概览页包含指数、板块热力图、资金流向、涨跌统计

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 自选股 CRUD | 添加、移除操作正常，列表持久化 |
| 2 | 自选股数据 | 行情数据（价格、涨跌幅等）正确显示 |
| 3 | 排序 | 点击表头可按涨跌幅/换手率等排序 |
| 4 | 指数卡片 | 4 个指数数据正确，迷你图渲染 |
| 5 | 热力图 | TreeMap 渲染正常，颜色和面积映射合理 |
| 6 | 资金流向 | 柱状图数据方向正确（正值红、负值绿） |
| 7 | 页面加载 | 大盘页打开 <3s 完成数据加载和渲染 |

---

## 阶段 8: AI 集成与打磨

### 目标

接入 LLM AI 分析能力，完善设置页面，优化 UI 细节，准备打包发布。

### 任务清单

#### 8.1 AI 分析服务

- [x] 创建 `backend/services/ai_analyzer.py` — `AIAnalyzer` 类:
  - [x] LLM 客户端初始化（支持 Claude / OpenAI，通过配置切换）
  - [x] `analyze_news_sentiment(news_list)` — 新闻情绪分析
  - [x] `generate_analysis_report(stock_data)` — 综合分析报告
  - [x] `generate_portfolio_advice(portfolio_data)` — 持仓诊断建议
  - [x] 错误处理: API 调用失败时返回 None，上层降级处理

- [x] 创建 Prompt 模板:
  - [x] `backend/config/prompts/news_sentiment.txt`
  - [x] `backend/config/prompts/stock_report.txt`
  - [x] `backend/config/prompts/portfolio_advice.txt`
  - 模板中使用 `{variable}` 占位符

- [x] 集成到报告生成流程:
  - [x] `ReportBuilder.build_report()` 中增加 AI 分析步骤
  - [x] 有 API Key → 调用 AI → 评分权重 35/35/30
  - [x] 无 API Key 或失败 → 跳过 → 权重 50/50，报告中标注"AI 分析不可用"

- [x] 集成到持仓风险:
  - [x] `GET /api/portfolio/risk/ai-advice` — AI 持仓建议
  - [x] RiskDashboard 底部增加 AI 建议卡片

#### 8.2 前端 AI 内容填充

- [x] 完善 `SentimentCard`:
  - [x] 新闻情绪分布饼图 (利好/利空/中性)
  - [x] 关键事件列表（标题 + 情绪标签 + 影响描述）
  - [x] AI 情绪摘要段落

- [x] 完善 `ConclusionCard`:
  - [x] AI 综合分析段落
  - [x] 风险提示列表（红色图标）
  - [x] 潜在催化因素列表（绿色图标）
  - [x] 操作建议段落

#### 8.3 设置页面

- [x] `pages/Settings/index.tsx`:
  - [x] **股票数据源状态**：整合阶段 3 的状态接口，显示来源、配置状态、数据日期、不可用能力和错误提示；密钥仍由后端环境变量管理
  - [x] **AI 配置区块**:
    - Provider 选择 (Claude / OpenAI / 自定义)
    - API Key 输入（密码框）
    - API Base URL（可选）
    - Model 选择下拉
    - 测试连接按钮
  - [x] **数据缓存区块**:
    - 缓存统计（文件数 / 总大小）
    - 清空缓存按钮
  - [x] **关于区块**:
    - 版本号
    - 技术栈信息
    - 项目链接

- [x] 实现配置 API:
  - [x] `GET /api/config` — 获取全部配置
  - [x] `PUT /api/config` — 更新配置
  - [x] `POST /api/config/test-llm` — 测试 LLM 连接

#### 8.4 UI 打磨

- [x] 亮色/暗色主题切换功能
- [x] 侧边栏收起/展开动画
- [x] 加载状态统一处理（Skeleton / Spin）
- [x] 错误状态统一处理（网络错误、后端错误友好提示）
- [x] 空状态统一处理（无数据时的引导页面）
- [x] 浏览器标签页标题动态更新（显示当前页面名称）

#### 8.5 生产部署配置

- [x] 前端 `npm run build` 构建静态文件到 `frontend/dist/`
- [x] FastAPI 添加 `StaticFiles` 托管前端静态文件（生产模式，单进程运行）
- [x] 完善 `start.sh` 一键启动脚本
- [x] 测试: 生产模式下只启动后端，浏览器访问 `localhost:18900` 功能正常

### 交付物

- AI 分析功能集成完毕，报告中有 AI 生成的分析内容
- 设置页面可配置 API Key 并测试连接
- UI 细节打磨完毕
- 生产模式可单进程运行（FastAPI 托管前端静态文件）

### 审核检查点

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | AI 新闻分析 | 配置 API Key 后，报告中新闻情绪分析有内容 |
| 2 | AI 综合报告 | AI 生成的分析文字通顺、与数据一致 |
| 3 | AI 降级 | 不配置 Key 时，报告正常生成，标注"AI 不可用" |
| 4 | AI 持仓建议 | 持仓页面显示 AI 诊断建议 |
| 5 | LLM 测试 | 设置页点击测试连接，成功/失败有明确提示 |
| 6 | 主题切换 | 亮/暗主题切换后所有页面显示正常 |
| 7 | 生产模式 | `npm run build` 后只启动后端，浏览器访问 `localhost:18900` 功能正常 |
| 8 | 免责声明 | 报告底部免责声明始终显示 |

---

## 阶段间依赖关系

```
阶段1 (骨架，已完成)
  └→ 阶段2 (数据桩与缓存，已完成)
       └→ 阶段3 (双源股票 API 对接，新增)
            ├→ 阶段4 (分析引擎)
            │    ├→ 阶段5 (报告前端)
            │    └→ 阶段6 (持仓风险)
            └→ 阶段7 (看板大盘)
  阶段5 + 阶段6 + 阶段7 完成后
       └→ 阶段8 (AI + 打磨)
```

- 阶段 4、7 均依赖阶段 3 的真实数据与缺失契约；阶段 7 可与阶段 4–6 并行开发。
- 阶段 5、6 依赖阶段 4，二者可以并行。
- 阶段 6 使用未复权价格估值、同口径复权收益率计算风险，并核对股票/基准共同交易日及数据缺口。
- 阶段 7 必须落实阶段 3 记录的行业/大盘资金/涨跌统计缺口；数据缺失时显示不可用和覆盖率。
- 阶段 8 仅在可靠关联新闻存在时计算新闻情绪，无新闻不按中性 0 分参与加权。
- 阶段 8 依赖全部前置功能；阶段 3 的扩展能力缺口需保持可追踪，不能被页面占位掩盖。

---

## Agent 使用指南

每个阶段可以交给一个独立 agent 实现。给 agent 的 prompt 应包含:

1. **读取设计文档**: "请先阅读 `docs/design.md`，理解系统整体架构"
2. **明确阶段范围**: "你负责实现阶段 X 的全部任务"
3. **检查前置交付物**: "请按依赖图验证本阶段所有前置交付物；阶段 3 还需读取两份 TXT 手册和接口验收记录"
4. **逐项完成**: "按任务清单逐项实现，每完成一项标记 done"
5. **自测**: "完成后按审核检查点逐项自测"
6. **不要越界**: "不要修改其他阶段的代码，不要提前实现后续阶段的功能"

---

## 审核流程

每个阶段完成后，由审核者（你）执行:

1. **代码审查**: 检查代码质量、是否符合设计文档
2. **功能验证**: 按审核检查点逐项验证
3. **集成测试**: 验证与已完成阶段的集成是否正常
4. **反馈**:
   - 通过 → 进入下一阶段
   - 不通过 → 列出具体问题，agent 修复后重新审核
5. **计划调整**: 如果发现设计需要调整，先更新 `design.md`，再继续实现
