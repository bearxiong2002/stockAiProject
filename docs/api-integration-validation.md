# 股票 API 对接验收记录（阶段 3，脱敏）

> 生成日期：2026-09-13（周日，非交易日；所有数据时间锚定最近已完成交易日 **2026-09-11**）
> 验收方式：双源独立探测 → 单位/复权交叉校准 → 冷启动 smoke → 离线契约测试 → 后端 curl 回归。
> 本记录不含密钥：所有真实请求密钥只出现在 `X-API-Key` 请求头中，来自 `backend/.env`（gitignored）。

## 1. 结论摘要

| 项 | 结论 |
| --- | --- |
| Datahubco 基础版（主源） | **20/20 探测通过**，含全部核心接口（列表/日历/日线/估值/复权/财务三表/指标/分红/个股资金/涨跌停/申万分类） |
| ProMax 中继（备源） | 能力目录 19/19 通过；正式查询 14/15 通过，`major_news` 上游池耗尽（503 upstream_pool_exhausted，非权限问题） |
| 正式 smoke（17 方法） | **22 verified / 1 degraded / 0 unavailable**（degraded = 个股新闻，上游当前无数据，如实降级） |
| 离线契约测试（httpx MockTransport） | 33/33 通过 |
| 阶段 2 回归自测（锁定 mock） | 49/49 通过 |
| 密钥合规 | 仅后端请求头；不入源码/日志/缓存/前端；错误对象与探测输出全部脱敏 |

## 2. 探测验收（最小连通性，正式请求口径）

探测脚本：`backend/tests/probe_real_apis.py`（结果存于 `/tmp/stockpanel_probe_results.json`，55 项）。
分类口径：**formal**=正式业务请求（带代码/日期/交易日等筛选）；**catalog**=ProMax 能力目录。
探测仅验证连通与权限，不作为生产默认值依据；正式功能以 smoke 为准。

### 2.1 Datahubco 基础版（20/20 通过，HTTP 200 + code=0）

| 接口 | 脱敏参数 | 返回行数 | 说明 |
| --- | --- | --- | --- |
| trade_cal | exchange=SSE，近 30 天 | 31 | 交易日历；`X-Cache: HIT`、`X-Request-ID` 回传 |
| stock-basic（用户示例别名） | limit=3 | 3 | 与 stock_basic 返回**逐字段一致** |
| stock_basic（手册规范名） | limit=3 | 3 | 固定采用规范名，不做全局连字符替换 |
| stock_basic 带筛选 | list_status=L, limit=5 | 5 | 筛选参数生效 |
| daily 单日 | ts_code, trade_date | 1 | vol=手、amount=千元 |
| daily 区间 | ts_code, start/end | 7 | — |
| daily_basic 单日 | ts_code, trade_date | 1 | pe/pb/total_mv(万元) |
| adj_factor 区间 | ts_code, start/end | 7 | 复权因子 |
| index_daily 沪深300 | ts_code=000300.SH, 区间 | 7 | — |
| fina_indicator | ts_code, period=最新报告期 | 1 | — |
| income / balancesheet / cashflow | ts_code, period | 各 2 | report_type=1 合并报表 |
| dividend | ts_code, limit=5 | 5 | cash_div 每股口径 |
| moneyflow 个股资金 | ts_code, 区间 | 7 | 万元口径 |
| stk_limit 涨跌停价 | trade_date, limit=5 | 5 | 阶段 7 预留 |
| index_classify SW2021 L1 | limit=10 | 10 | 31 个一级行业（分页） |
| index_member_all 成分 | limit=5 | 0 | 空小样本；正式路径按 index_code 查询已验收 |
| index_weekly / index_monthly | ts_code, 区间 | 2 / 8 | 指数周/月可用（未纳入契约，备用） |

### 2.2 ProMax 中继（能力目录 19/19，正式 14/15）

能力目录（`GET /tushare/capabilities` 及 `/capabilities/{api}`）全部 HTTP 200：daily、daily_basic、adj_factor、pro_bar、news、major_news、top10_holders、sw_daily、moneyflow_mkt_dc、index_classify、index_member_all、dividend、trade_cal、stock_basic、income、fina_indicator、moneyflow、daily_basic、index_daily。

正式查询通过（HTTP 200 + code=0）：daily 区间 / daily 全市场单日 / adj_factor / pro_bar(qfq) / stock_basic(SSE) / trade_cal / index_daily / top10_holders(limit=10) / sw_daily / index_classify(31 行业) / index_member_all(按行业) / moneyflow_mkt_dc / dividend / news（200 但 0 行，见缺口）。

未通过：`major_news` → HTTP 503 `upstream_pool_exhausted`（多次、跨时段复现；属上游池耗尽可重试故障，非权限/参数错误）。

### 2.3 别名与路径核对（3.1 专项）

- `stock-basic`（用户示例）与 `stock_basic`（手册）返回**同一数据、同一字段序**，确认为已验证路径别名；代码固定使用规范名 `stock_basic`，未做任何全局连字符替换。
- ProMax 能力目录不位于 `/tushare/pro` 下，代码从 `/tushare/pro` 推导 `/tushare/capabilities`，与文档一致。
- `__probe=1` 仅探测期使用；正式实现中无业务筛选的接口显式 `__probe=0`（`_NON_FILTER_KEYS = {limit, offset, fields, __probe}` 不视为业务筛选）。

## 3. 上游限制实测（影响实现的硬约束）

| 限制 | 实测 | 代码对策 |
| --- | --- | --- |
| 单代码/指数/申万日期区间 | >366 天 → 400 "date range exceeds 366 days"（二分实测） | `fetch_date_chunks` 350 天窗口，从后往前切窗 |
| 全市场单日查询 | 无 limit 时响应过大 → 413 "response is too large" | `fetch_all` 自适应减页 5000→2500→1250→625，<500 抛错 |
| 基础版 HTTP `pro_bar` | 手册明确不支持；实测确认 | 基础模式一律不调用；复权用 daily+adj_factor 本地计算 |
| ProMax pro_bar | 为本地聚合（非 tushare 直通），带 adjust 参数 | 仅作对照/备用路径；与本地复权交叉复算一致（见 §5） |
| 基础版 502 | 可能包装上游权限错误 | 502 不盲重试，按协议错误分类（解析 body 判别） |
| ProMax 503 | `data_source_unavailable` 不重试；`upstream_pool_exhausted` 可重试（指数退避 2 次） | 已按错误体分类 |
| 限流 | 配置 120 次/分钟、4 并发（`PROMAX_REQUESTS_PER_MINUTE`/`STOCK_MAX_CONCURRENCY`），0.5s 最小间隔 | 429 尊重 `Retry-After`；总预算 60s |

## 4. 单位校准（真实样本核验，3.3/3.4 专项）

| 字段 | 供应商口径 | 契约口径 | 换算 | 核验样本 |
| --- | --- | --- | --- | --- |
| daily.vol | 手 | 股 | ×100 | 平安银行 832,460 手 ↔ 9.8 亿元成交额 ↔ turnover 三方自洽 |
| daily.amount | 千元 | 元 | ×1000 | 全市场单日合计 ≈ 19,870 亿 |
| moneyflow（个股） | 万元 | 亿元 | ÷1e4 | 超大+大净额 = 主力净额；四类单和≈0 |
| moneyflow_mkt_dc | 元 | 亿元 | ÷1e8 | net_amount=主力=超大+大 |
| daily_basic.total_mv / circ_mv | 万元 | 亿元 | ÷1e4 | 市值=股本×价 复核通过 |
| daily_basic.total_share / float_share | 万股 | 亿股 | ÷1e4 | 茅台 12.5008 亿股 |
| sw_daily.amount | 万元 | 亿元 | ÷1e4 | 31 行业合计 ≈ 19,627 亿 ≈ 全市场口径；vol 单位无权威解释，保留原值并注记 |
| dividend.cash_div | 每股（元） | 每 10 股 | ×10 | 茅台 2023 年报 30.876 元/股 → 308.76 元/10 股（公开信息核对一致） |
| top10_holders.hold_amount | 股（字符串） | 万股 | ÷1e4 | 供应商返回字符串，已数字化 |
| index_daily.amount / vol | 千元 / 股 | 元 / 股 | ×1000 / 原值 | 指数 volume 单位注记保留 |

## 5. 复权与聚合复算（3.3 专项）

- **前复权公式**：`P_qfq = P × F(t) / F(anchor)`，anchor=窗口内最近有效因子。分窗（350 天）合并后必须先 `sort_values` 再取锚点（已修复的锚点 bug：合并乱序时 `iloc[-1]` 取到旧因子）。
- **交叉复算**：本地 daily+adj_factor 前复权 vs ProMax `pro_bar(adjust=qfq)`，茅台 29 个交易日收盘价**最大相对偏差 0.0000%**；锚点日未复权 close=1275.16 与实时价一致。
- **后复权**：`P_hfq = P × F(t)`；不复权直接取原价。
- **周/月聚合**：ISO 周 / 自然月重采样；容忍指数、行业序列缺失 turnover 列。
- 期末样本：`cross_check(pro_bar qfq)` verified；三种复权与周/月聚合均 smoke verified（282 日 / 60 周 / 15 月）。

## 6. 正式 smoke 结果（冷缓存，17 方法）

脚本：`backend/tests/smoke_real_apis.py`（`STOCKPANEL_SMOKE=1` 显式启用；结果写入 `<DATA_DIR>/data_source_status.json`）。
样本：`600519.SH`（有除权史）、`000001.SZ`、北交所股票、`000300.SH` 基准。

| 方法 | 状态 | 行数 | 数据时间 | 主源 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| get_stock_list（沪深北去重） | verified | 5562（北交所 343） | — | datahubco | 15252ms |
| get_kline daily/qfq | verified | 282 | 2026-09-11 | datahubco | 4067ms |
| get_kline weekly / monthly / 不复权 / 北交所 | verified | 60 / 15 / 282 / 282 | 2026-09-11 | datahubco | 3496–6232ms |
| get_financial_indicator | verified | 8 | 2026-06-30 | datahubco | 502ms |
| get_profit_sheet / balance / cashflow | verified | 各 8 | 2026-06-30 | datahubco | 345–813ms |
| get_index_data 日 / 周 | verified | 282 / 60 | 2026-09-11 | datahubco | 2054 / 1041ms |
| get_fund_flow | verified | 30 | 2026-09-11 | datahubco | 1227ms |
| get_market_fund_flow | verified | 30 | 2026-09-11 | promax | 1667ms |
| get_holder_info（十大股东） | verified | 10 | 2026-06-30 | promax | 76ms |
| get_dividend_history | verified | 30 | 2025-12-31 | datahubco | 1463ms |
| get_industry_board_list（31 行业+领涨股） | verified | 31 | 2026-09-11 | datahubco | 16786ms（冷启动含全市场行情） |
| get_industry_board_hist | verified | 282 | 2026-09-11 | promax | 3119ms |
| get_stock_news | **degraded** | 0 | — | promax | 5197ms |

degraded 说明：news 两种时间窗格式均返回空结果（上游当前无数据），major_news 持续 503 池耗尽；按设计降级为空列表 + warning，未用 mock 顶替。

## 7. 缓存与性能（3.5 专项）

- 缓存 v2：`<CACHE_DIR>/<provider>/<subdir>/`，键 = provider + schema_version(3) + 方法 + 参数（含 fields 顺序/adjust/锚点）；`_data_meta`（source/api/as_of/trade_date/fetched_at/is_stale/coverage/warnings）随数据序列化。
- 空 result 60s 短缓存；同 key 并发合并；唯一临时文件原子写；stale 回退仅限可恢复故障（72h 窗口）且标注 `is_stale`。
- 阶段 2 的无来源标记缓存不能进入真实模式（provider 目录隔离 + schema 版本）。

| 场景 | 冷启动 | 热缓存 |
| --- | --- | --- |
| /api/stock/list（5562 只） | 15252ms（含申万行业补齐） | **64ms** |
| /api/stock/600519/kline?days=30 | ~4000ms | **16ms** |
| 上游请求数 | 冷启动一次性，其后全部命中缓存 | 0 |

## 8. API 层回归（3.6，真实模式 hybrid）

| 端点 | 结果 |
| --- | --- |
| GET /api/stock/search?q=茅台 | 600519 命中；响应头 `X-Data-Source: datahubco`、`X-Data-Stale: 0` |
| GET /api/stock/search?q=600 | 代码前缀匹配正常，≤20 条 |
| GET /api/stock/list | 5562 条真实数据 |
| GET /api/stock/600519/info | 真实估值（close 1275.16、PE 19.57、PB 6.34、总股本 12.5008 亿股）+ data_meta |
| GET /api/stock/600519/kline?days=30 | 44 条 qfq 真实 K 线 + data_meta（api=daily+daily_basic+adj_factor，anchor=8.6463） |
| GET /api/config/data-source-status | 模式/双端配置/逐方法验证结论，无密钥回传 |
| GET /api/config/cache-stats + DELETE /api/config/cache | 5 文件 672KB → 清空 0 |
| GET /api/health | 200 |

## 9. 测试矩阵（3.6 专项）

| 套件 | 触发 | 联网 | 结果 |
| --- | --- | --- | --- |
| tests/test_offline_contract.py | 默认 | 否（httpx MockTransport） | 33/33：信封/错误分类/429 Retry-After/分页终止/deadline/单位/复权复算/缺测 |
| tests/selftest_phase2.py | 默认（锁定 mock 模式） | 否 | 49/49：17 方法契约 + 缓存写入/清理 |
| tests/smoke_real_apis.py | `STOCKPANEL_SMOKE=1` | 是 | 22 verified / 1 degraded / 0 unavailable |

## 10. 缺口与后续事项（如实记录，不宣称全量可用）

| 缺口 | 影响 | 后续 |
| --- | --- | --- |
| ProMax `major_news` 持续 503 pool_exhausted | 市场快讯不可用 | 上游恢复后自动可用；`get_stock_news` 已含该源 |
| ProMax `news` 当前 0 行 | 个股新闻暂为空列表+warning | 上游数据恢复后无需改代码 |
| sw_daily `vol` 单位无权威解释 | 行业成交量保留原值+注记 | 阶段 4 技术分析仅用金额/涨跌幅，不受影响 |
| `index_weekly/monthly` 未纳入 17 方法契约 | 仅备用验证 | 已验证可用，阶段 4 风险窗口可按需启用 |
| 新闻/行业领涨股为可选能力 | 失败返回空+warning，不阻塞核心 | 阶段 5/7/8 对应待办跟进 |

## 11. 密钥与传输合规（3.2/检查点 11）

- 密钥仅存 `backend/.env`（`DATAHUBCO_API_KEY` / `PROMAX_API_KEY`），`.gitignore` 已覆盖 `backend/.env`；`.env.example` 仅占位值。
- 请求时密钥只放 `X-API-Key` 请求头；日志、错误对象（`to_dict`）、缓存、探测/smoke 输出、API 响应均不含密钥。
- 传输：ProMax HTTPS 默认校验证书（`STOCK_TLS_VERIFY=1`，可配 CA）；Datahubco 为明文 HTTP，需显式 `DATAHUBCO_ALLOW_HTTP=true` 才允许启动（配置缺失时报 503 明确原因，不静默降级 mock）。

## 12. 代码审查修复记录（阶段 3 交付后）

外部代码审查提出 14 项，逐项核实后 **12 项属实并已修复，1 项误报，1 项列为已知取舍**；修复过程中连带发现并修复 1 个单位换算 bug。修复后缓存 schema 版本升级 **v4**（旧口径缓存整体失效重建），离线契约测试 33/33、阶段 2 自测 49/49 回归通过，后端 curl 回归通过。

| # | 判定 | 修复 |
| --- | --- | --- |
| 1 | 属实 | `fetch_all` 413 减页条件补括号（`and` 优先级）；另在 `_parse_error` 为上游 413 增加显式分类（JSON/非 JSON 两条路径均含 "413" 字样），减页序列实测 2000→1000→500 |
| 2 | 属实（严重） | `daily_amounts` 缓存键补入 `ts`，不同股票不再共享成交额；实测 600519 与 000001 主力净额各自独立 |
| 3 | 属实 | `fetch_date_chunks` 下一窗游标改为 `_shift_days(win_start, 1)`；验证 2 年区间 3 窗无重叠、无重复日期、覆盖完整 |
| 4 | 属实 | 新增 `get_data_fetcher()` 进程级单例，`api/config.py` 不再每请求新建；`api/stock.py` 同步复用 |
| 5 | 属实 | `DataFetcher.close()` + `main.py` lifespan shutdown 关闭已创建的 httpx 连接池 |
| 6 | 属实 | `capabilities_catalog` 纳入并发信号量 + 限流器，异常经 `_parse_error` 分类 |
| 7 | 属实 | `moneyflow_df` 主力净额任一单缺失 → null（不再 fillna(0)）；缺测/齐全两条路径均有测试 |
| 8 | 属实 | `_route/_route_optional` 增加 `dh_name/pm_name` 标注；holder/news 等 promax 专属能力日志不再误标 datahubco |
| 9 | 属实 | `DataFetcher` 真实客户端懒加载（property），mock 模式零 HTTP 连接池 |
| 10 | 属实 | inflight 锁先在 guard 内注销、后 release，消除双跑竞态窗口 |
| 11 | 属实 | `datetime` 提升到 baseclient 模块顶层 |
| 12 | 取舍 | 自写 runner 保留（计数式可一次看全部失败；pytest 迁移列入后续改进，不阻塞） |
| 13 | 属实 | `resample_period._sum` 显式接收分组数据，不再闭包捕获循环变量 |
| 14 | 误报 | 手册 §8.5 明确"新闻时间可以写成 YYYYMMDD、YYYY-MM-DD 或完整时间"，当前格式合规 |
| 连带 | 新发现 | `main_net_inflow_pct` 单位换算缺失（主力净额亿元 ÷ 成交额元）→ 修正为 ×1e8 对齐；茅台实测 -4.36%（此前错误显示 -0.0%） |
