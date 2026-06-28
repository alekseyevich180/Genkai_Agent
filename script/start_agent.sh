#!/usr/bin/env bash
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJ_ROOT/logs"
mkdir -p "$LOG_DIR"

cleanup() {
    echo ""
    echo "Shutting down services..."
    [[ -n "${PID_API:-}" ]] && kill "$PID_API" 2>/dev/null || true
    [[ -n "${PID_WEB:-}" ]] && kill "$PID_WEB" 2>/dev/null || true
    [[ -n "${PID_VITE:-}" ]] && kill "$PID_VITE" 2>/dev/null || true
    wait 2>/dev/null || true
    echo "All services stopped."
}
trap cleanup SIGINT SIGTERM

ensure_running() {
    local pid="$1"
    local name="$2"
    local log_file="$3"

    if ! kill -0 "$pid" 2>/dev/null; then
        echo ""
        echo "$name failed to start. Last log lines:"
        tail -n 40 "$log_file" || true
        cleanup
        exit 1
    fi
}

cd "$PROJ_ROOT"

echo "Starting ADK API server (port 8000)..."
agent api-server >"$LOG_DIR/api-server.log" 2>&1 &
PID_API=$!
sleep 1
ensure_running "$PID_API" "ADK API server" "$LOG_DIR/api-server.log"

echo "Starting FastAPI middle layer (port 8001)..."
python web/main.py >"$LOG_DIR/web-main.log" 2>&1 &
PID_WEB=$!
sleep 1
ensure_running "$PID_WEB" "FastAPI middle layer" "$LOG_DIR/web-main.log"

echo "Starting Vite frontend (port 5173)..."
cd "$PROJ_ROOT/web/vite-frontend"
npm run dev >"$LOG_DIR/vite.log" 2>&1 &
PID_VITE=$!
sleep 1
ensure_running "$PID_VITE" "Vite frontend" "$LOG_DIR/vite.log"

echo ""
echo "All services running:"
echo "  ADK API server : http://localhost:8000"
echo "  FastAPI layer  : http://localhost:8001"
echo "  Frontend       : http://localhost:5173"
echo ""
echo "Logs: $LOG_DIR/{api-server,web-main,vite}.log"
echo "Press Ctrl+C to stop all services."

wait
