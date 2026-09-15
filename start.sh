#!/bin/bash
# StockPanel 一键启动脚本
#
#   ./start.sh          开发模式: Python 后端(18900) + Vite 前端(5173)
#   ./start.sh prod     生产模式: 构建前端后仅启动后端，浏览器访问 http://localhost:18900
#   ./start.sh build    仅构建前端静态文件到 frontend/dist
#
# 端口可覆盖: STOCKPANEL_PORT=18901 STOCKPANEL_FRONTEND_PORT=5174 ./start.sh
#   前端 Vite 的代理目标会跟随 STOCKPANEL_PORT，无需改配置。
# 依赖: bash + curl + python3 >= 3.10 + node >= 18 + npm (+ lsof 用于端口占用提示，可选)

set -e

MODE="${1:-dev}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
PORT="${STOCKPANEL_PORT:-18900}"
FRONTEND_PORT="${STOCKPANEL_FRONTEND_PORT:-5173}"
# vite.config.ts 从这两个变量读取代理目标与开发端口
export STOCKPANEL_BACKEND_URL="${STOCKPANEL_BACKEND_URL:-http://localhost:$PORT}"
export STOCKPANEL_FRONTEND_PORT="$FRONTEND_PORT"

die() { echo "错误: $*" >&2; exit 1; }

check_prereqs() {
  command -v python3 > /dev/null 2>&1 || die "未找到 python3，请先安装 Python 3.10 或更高版本"
  command -v curl > /dev/null 2>&1 || die "未找到 curl（用于后端就绪探测）"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "需要 Python 3.10 及以上，当前为 $(python3 -V 2>&1)"
  command -v node > /dev/null 2>&1 || die "未找到 node，请先安装 Node.js 18 或更高版本"
  command -v npm > /dev/null 2>&1 || die "未找到 npm（随 Node.js 安装）"
}

port_busy() {
  command -v lsof > /dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$1" -sTCP:LISTEN > /dev/null 2>&1
}

warn_port() {
  if port_busy "$1"; then
    echo "警告: 端口 $1 已被占用$2"
  fi
}

ensure_backend() {
  cd "$BACKEND_DIR"
  if [ ! -d ".venv" ]; then
    echo "未检测到虚拟环境，正在创建..."
    python3 -m venv .venv \
      || die "创建虚拟环境失败（Debian/Ubuntu 需先执行 apt install python3-venv）"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -r requirements.txt -q
  else
    # shellcheck disable=SC1091
    source .venv/bin/activate
  fi
  command -v uvicorn > /dev/null 2>&1 \
    || die "虚拟环境缺少 uvicorn，请执行 backend/.venv/bin/pip install -r requirements.txt"
}

install_frontend_deps() {
  cd "$FRONTEND_DIR"
  if [ -d "node_modules" ]; then
    return 0
  fi
  echo "未检测到 node_modules，正在安装依赖..."
  if [ -f "package-lock.json" ]; then
    npm ci          # 有锁文件时按锁文件安装，保证与其他机器一致
  else
    npm install
  fi
}

build_frontend() {
  install_frontend_deps
  echo ">>> 构建前端静态文件 (frontend/dist) ..."
  npm run build
}

wait_backend() {
  echo "等待后端就绪..."
  for i in $(seq 1 30); do
    if curl -s "http://localhost:$PORT/api/health" > /dev/null 2>&1; then
      echo "后端已就绪。"
      return 0
    fi
    sleep 1
  done
  echo "警告: 后端 30 秒内未响应。"
}

check_prereqs

if [ "$MODE" = "build" ]; then
  build_frontend
  echo "构建完成: $FRONTEND_DIR/dist"
  exit 0
fi

if [ "$MODE" = "prod" ]; then
  build_frontend
  ensure_backend
  echo ""
  warn_port "$PORT" "，请先停止占用进程或设置 STOCKPANEL_PORT 换端口"
  echo ">>> 启动后端 (生产模式, 托管 frontend/dist): http://localhost:$PORT"
  uvicorn main:app --host 0.0.0.0 --port "$PORT"
  exit 0
fi

# 后台任务各自独立进程组，cleanup 时整组结束，避免子进程残留占用端口
set -m

cleanup() {
  echo ""
  echo "正在关闭服务..."
  kill -- "-$BACKEND_PID" 2>/dev/null || true
  kill -- "-$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "已停止。"
}
trap cleanup EXIT INT TERM

warn_port "$PORT" "，可在前面加 STOCKPANEL_PORT=18901 换端口"
warn_port "$FRONTEND_PORT" "，Vite 会自动顺延到下一个可用端口（以终端输出为准）"

# ---- 后端 ----
echo ">>> 启动后端 (FastAPI on :$PORT) ..."
ensure_backend
uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload &
BACKEND_PID=$!

wait_backend

# ---- 前端 ----
echo ">>> 启动前端 (Vite on :$FRONTEND_PORT) ..."
install_frontend_deps
npm run dev -- --host &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  StockPanel 已启动（开发模式）"
echo "  前端: http://localhost:$FRONTEND_PORT"
echo "  后端: http://localhost:$PORT"
echo "  生产模式: ./start.sh prod  (仅后端 + 静态托管)"
echo "  按 Ctrl+C 停止所有服务"
echo "========================================"

wait
