# StockPanel 启动指南

## 项目结构

```
stockPanel/
├── frontend/          # React + Vite 前端
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx           # 入口
│       ├── App.tsx            # 路由
│       ├── components/        # 通用组件
│       ├── pages/             # 页面（5 个）
│       ├── services/api.ts    # axios 实例
│       ├── stores/backend.ts  # 后端状态管理
│       ├── styles/global.css  # 全局样式
│       └── types/index.ts     # 类型定义
│
├── backend/           # Python FastAPI 后端
│   ├── main.py              # FastAPI 入口
│   ├── requirements.txt     # Python 依赖
│   ├── .env                 # 本地密钥配置（gitignored，参考 .env.example）
│   ├── config/settings.py   # 应用配置（数据源/缓存/限流）
│   ├── models/              # 数据库 & Pydantic schemas
│   ├── api/                 # API 路由（stock/portfolio/watchlist/market/config）
│   ├── config/prompts/      # LLM Prompt 模板（news_sentiment / stock_report / portfolio_advice）
│   ├── services/            # data_fetcher + providers/（datahubco/promax/mock）+ ai_analyzer + llm_config
│   └── tests/               # 离线契约/引擎测试、各阶段自测、mock LLM 服务、真实 smoke（opt-in）
│
└── docs/              # 设计文档
    ├── design.md              # 系统设计文档
    ├── implementation-plan.md # 分阶段实现计划
    ├── api-integration-validation.md # 数据源对接验收记录（阶段 3）
    └── startup.md             # 本文件
```

## 环境要求

| 依赖     | 版本要求    | 说明                   |
| -------- | ----------- | ---------------------- |
| Node.js  | >= 18       | 前端构建               |
| Python   | >= 3.10     | 后端运行               |
| npm      | >= 9        | 随 Node.js 安装        |

`./start.sh` 启动前会校验上述依赖与 Python 版本，缺失时直接给出中文提示而不是运行中途报错。
脚本为 bash 脚本（激活 `.venv/bin/activate`），Windows 需用 WSL 或 Git Bash。

## 一、后端启动

### 1. 创建虚拟环境并安装依赖

```bash
cd stockPanel/backend

# 如果 .venv 不存在则创建
python3 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动后端服务

```bash
cd stockPanel/backend
source .venv/bin/activate

uvicorn main:app --host 0.0.0.0 --port 18900 --reload
```

启动成功后终端会输出：

```
INFO:     Uvicorn running on http://0.0.0.0:18900
INFO:     stockpanel: backend started, db=...stockpanel.db
```

### 3. 验证后端

浏览器访问 http://localhost:18900/api/health ，应返回：

```json
{"status": "ok", "version": "0.1.0", "app": "StockPanel Backend"}
```

## 二、前端启动

### 1. 安装依赖

```bash
cd stockPanel/frontend
npm install
```

### 2. 启动开发服务器

```bash
cd stockPanel/frontend
npm run dev
```

启动后访问 http://localhost:5173

> Vite 开发服务器会自动将 `/api/*` 请求代理到 `http://localhost:18900`，无需手动处理跨域。

## 三、一键启动（推荐）

```bash
./start.sh          # 开发模式: 后端 18900 + Vite 5173（自动建 venv/装依赖/等后端就绪）
./start.sh prod     # 生产模式: 构建前端后仅启动后端，访问 http://localhost:18900
./start.sh build    # 仅构建前端静态文件到 frontend/dist
```

也可以手动分别启动：

```bash
# 终端 1 — 后端
cd stockPanel/backend && source .venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 18900 --reload
# 终端 2 — 前端
cd stockPanel/frontend && npm run dev
```

## 四、生产构建

### 前端打包

```bash
cd stockPanel/frontend
npm run build
```

产物输出到 `frontend/dist/`。

### 生产部署（阶段 8 已实现）

`frontend/dist/index.html` 存在时，后端自动挂载前端静态资源（SPA 未命中路由回退 `index.html`，
`/api/*` 仍优先走接口，未知 `/api` 路径返回 404 而非 HTML）；`index.html` 不缓存，发版后立即生效。
可用 `STOCKPANEL_SERVE_STATIC=true|false` 显式开关，`STOCKPANEL_FRONTEND_DIST` 覆盖目录。

生产模式启动（单进程，只需后端）：

```bash
cd stockPanel && ./start.sh prod
# 等价于: cd frontend && npm run build && cd ../backend && uvicorn main:app --host 0.0.0.0 --port 18900
```

访问 http://localhost:18900 即可使用；设置页"关于"区块会显示"生产模式"。

## 五、数据源与环境变量

### 1. 数据源模式（阶段 3）

`STOCK_DATA_MODE` 决定后端取数方式，**更改后需重启**：

| 模式 | 行为 |
| --- | --- |
| `mock` | 阶段 2 模拟数据（默认；不联网，用于开发/测试） |
| `datahubco` | 仅基础版主源（明文 HTTP，需显式允许） |
| `promax` | 仅 ProMax 中继 |
| `hybrid` | 按接口固定主备路由（推荐生产模式；仅可重试故障时换源） |

### 2. 配置步骤

```bash
cd stockPanel/backend
cp .env.example .env
# 编辑 .env，填入你自己的密钥（见下方变量表）
```

`.env` 已被 `.gitignore` 覆盖，密钥不会入库。密钥只在请求头 `X-API-Key` 中使用，不写入日志/缓存/响应。

### 3. 变量表

| 变量名 | 默认值 | 说明 |
| --- | --- | --- |
| `STOCKPANEL_DATA_DIR` | macOS: `~/Library/Application Support/StockPanel` | 数据存储目录 |
| `STOCKPANEL_PORT` | `18900` | 后端服务端口 |
| `STOCKPANEL_FRONTEND_PORT` | `5173` | Vite 开发端口（仅开发模式；被占用时 Vite 自动顺延） |
| `STOCKPANEL_BACKEND_URL` | 跟随 `STOCKPANEL_PORT` | 开发模式 `/api` 代理目标（由 `start.sh` 注入，一般不用手设） |
| `STOCK_DATA_MODE` | `mock` | 数据源模式（见上表） |
| `DATAHUBCO_API_KEY` | 空 | Datahubco 基础版密钥（仅本地配置） |
| `DATAHUBCO_ALLOW_HTTP` | `false` | 基础版为明文 HTTP，必须显式置 `true` 才启用 |
| `PROMAX_API_KEY` | 空 | ProMax 中继密钥（仅本地配置） |
| `STOCK_TLS_VERIFY` | `1` | ProMax HTTPS 证书校验（`0` 不建议，可配 `STOCK_CA_FILE`） |
| `STOCK_MAX_CONCURRENCY` | `4` | 上游最大并发 |
| `PROMAX_REQUESTS_PER_MINUTE` | `120` | ProMax 限流预算 |
| `STOCK_STALE_MAX_AGE` | `72`（小时） | 故障时允许回退的旧缓存最大龄 |
| `STOCK_CACHE_SCHEMA_VERSION` | `4` | 缓存结构版本（改动数据口径时升级；v4 含主力净额缺测口径与切窗重叠修复） |
| `LLM_PROVIDER` | `none` | LLM 供应商: `claude` / `openai` / `custom` / `none`（设置页保存的值优先于环境变量） |
| `LLM_API_KEY` | 空 | LLM 密钥（设置页保存时加密写入 SQLite，优先于环境变量） |
| `LLM_API_BASE` | 空 | API 地址；留空用默认（claude=`https://api.anthropic.com`，openai=`https://api.openai.com/v1`） |
| `LLM_MODEL` | 空 | 模型名；留空用默认（设置页提供建议列表） |
| `LLM_READ_TIMEOUT` | `45`（秒） | 单次 LLM 调用读超时 |
| `LLM_MAX_TOKENS` | `1600` | 单次调用最大输出 token |
| `STOCKPANEL_SERVE_STATIC` | 自动 | 是否由后端托管 `frontend/dist`（未设置时 dist 存在即启用） |
| `STOCKPANEL_FRONTEND_DIST` | `../frontend/dist` | 前端构建产物目录 |

### 4. 验证真实数据

```bash
# 健康检查
curl http://localhost:18900/api/health

# 数据源配置与最近验证结论（不回传密钥）
curl http://localhost:18900/api/config/data-source-status

# 真实搜索（hybrid 模式返回响应头 X-Data-Source / X-Data-As-Of / X-Data-Stale）
curl "http://localhost:18900/api/stock/search?q=%E8%8C%85%E5%8F%B0"

# 缓存状态与清理
curl http://localhost:18900/api/config/cache-stats
curl -X DELETE http://localhost:18900/api/config/cache

# 系统配置（LLM 脱敏视图，不含密钥明文）
curl http://localhost:18900/api/config

# 配置 LLM（密钥加密存储；provider 传 none 可关闭 AI）
curl -X PUT http://localhost:18900/api/config -H 'Content-Type: application/json' \
  -d '{"llm_provider":"claude","llm_api_key":"sk-...","llm_model":"claude-sonnet-5"}'

# 测试 LLM 连接（成功/失败均返回明确分类）
curl -X POST http://localhost:18900/api/config/test-llm -H 'Content-Type: application/json' -d '{}'

# AI 持仓诊断（需先配置 LLM；结果缓存 10 分钟，force=true 强制刷新）
curl "http://localhost:18900/api/portfolio/risk/ai-advice"
```

接口逐项验收记录见 [api-integration-validation.md](./api-integration-validation.md)。

### 5. mock/real 切换与回退

- 切换模式：改 `.env` 的 `STOCK_DATA_MODE` 后重启（缓存按 provider 目录隔离，无串数据）。
- 真实模式缺密钥/未允许 HTTP：启动后首次请求返回 503 并说明配置原因，**不会静默降级为 mock**。
- 回退到 mock：`STOCK_DATA_MODE=mock` 重启即可；SQLite 持仓/自选数据不受影响。

## 六、AI 配置与验证（阶段 8）

### 1. 在设置页配置（推荐）

「设置 → AI 配置」选择 Provider（Claude / OpenAI / 自定义 OpenAI 兼容端）、填入 API Key（密码框）、
可选 Base URL 与 Model，点击「测试连接」验证后再保存。保存的密钥使用本机密钥文件
（`<数据目录>/secret.key`，权限 0600）加密后写入 SQLite `config` 表，接口只返回掩码 `sk-****1234`，
不回显明文、不写日志。配置优先级：SQLite（设置页） > 环境变量/.env > 默认值。

未配置或调用失败时：报告照常生成，综合评分回退技术面/基本面 50/50 权重，并在报告中标注
「AI 分析不可用」；持仓页显示未配置提示并可跳转设置页。

### 2. 离线验证 AI 链路（不消耗真实额度）

```bash
# 终端 A: 本地 Mock LLM（OpenAI 兼容，按 Prompt 返回固定结构化结果）
cd backend && .venv/bin/python tests/mock_llm_server.py 18999

# 终端 B: 配置指向 Mock 服务
curl -X PUT http://localhost:18900/api/config -H 'Content-Type: application/json' \
  -d '{"llm_provider":"custom","llm_api_key":"mock-key","llm_api_base":"http://127.0.0.1:18999/v1","llm_model":"mock-model"}'
```

之后生成报告可见 AI 情绪饼图/关键事件、AI 综合分析（风险/催化/操作建议）与持仓 AI 诊断。
验证完成后可在设置页「清除密钥」并把 Provider 切回"不使用 AI"。

### 3. 测试脚本

```bash
cd backend
.venv/bin/python tests/selftest_phase8.py     # 阶段8 离线自测（MockTransport，不联网）
.venv/bin/python tests/selftest_phase2.py     # 回归: 阶段2
.venv/bin/python tests/selftest_phase4.py     # 回归: 阶段4
.venv/bin/python tests/selftest_phase6.py     # 回归: 阶段6
.venv/bin/python tests/selftest_phase7.py     # 回归: 阶段7
.venv/bin/python tests/test_offline_contract.py   # 双源契约（httpx MockTransport）
```

## 七、常见问题

### 前端显示"后端服务连接失败"

确认后端是否已启动并监听 18900 端口：

```bash
curl http://localhost:18900/api/health
```

### 端口被占用

```bash
# 查看占用进程
lsof -i :18900
# 或更换端口
STOCKPANEL_PORT=18901 uvicorn main:app --host 0.0.0.0 --port 18901 --reload
```

更换后端端口时，需同步修改 `frontend/vite.config.ts` 中 proxy 的 target。

### AI 测试连接失败

- `auth`（401/403）：API Key 不正确 → 重新填写并保存。
- `model_not_found`（404）：模型名或 Base URL 不对 → 用设置页建议列表中的模型名。
- `timeout` / `network`：网络或代理问题；`http_error 502/503/504` 多为代理/网关不可达，
  检查 `LLM_API_BASE` 与系统代理（httpx 会读取系统代理，本机地址如 127.0.0.1 建议加入代理排除列表）。

### pip install 失败

建议使用国内镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
