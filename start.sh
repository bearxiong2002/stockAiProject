#!/bin/bash
# StockPanel 一键启动脚本
#
#   ./start.sh          开发模式: Python 后端(18900) + Vite 前端(5173)
#   ./start.sh prod     生产模式: 构建前端后仅启动后端，浏览器访问 http://localhost:18900
#   ./start.sh build    仅构建前端静态文件到 frontend/dist

set -e

MODE="${1:-dev}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
PORT="${STOCKPANEL_PORT:-18900}"

ensure_backend() {
  cd "$BACKEND_DIR"
  if [ ! -d ".venv" ]; then
    echo "未检测到虚拟环境，正在创建..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt -q
  else
    source .venv/bin/activate
  fi
}

build_frontend() {
  cd "$FRONTEND_DIR"
  if [ ! -d "node_modules" ]; then
    echo "未检测到 node_modules，正在安装依赖..."
    npm install
  fi
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

if [ "$MODE" = "build" ]; then
  build_frontend
  echo "构建完成: $FRONTEND_DIR/dist"
  exit 0
fi

if [ "$MODE" = "prod" ]; then
  build_frontend
  ensure_backend
  echo ""
  echo ">>> 启动后端 (生产模式, 托管 frontend/dist): http://localhost:$PORT"
  uvicorn main:app --host 0.0.0.0 --port "$PORT"
  exit 0
fi

cleanup() {
  echo ""
  echo "正在关闭服务..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
  echo "已停止。"
}
trap cleanup EXIT INT TERM

# ---- 后端 ----
echo ">>> 启动后端 (FastAPI on :$PORT) ..."
ensure_backend
uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload &
BACKEND_PID=$!

wait_backend

# ---- 前端 ----
echo ">>> 启动前端 (Vite on :5173) ..."
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  echo "未检测到 node_modules，正在安装依赖..."
  npm install
fi
npx vite --host &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  StockPanel 已启动（开发模式）"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:$PORT"
echo "  生产模式: ./start.sh prod  (仅后端 + 静态托管)"
echo "  按 Ctrl+C 停止所有服务"
echo "========================================"

wait
