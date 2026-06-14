#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
elif [[ -f "$ROOT_DIR/.env.example" ]]; then
  echo "Note: .env not found; using process environment and code defaults. .env.example is only a template."
fi

PID_FILE="$ROOT_DIR/.data/server.pid"
LOG_FILE="$ROOT_DIR/.data/logs/server.log"
HOST="${DOTS_API_HOST:-127.0.0.1}"
PORT="${DOTS_API_PORT:-8080}"
APP="dots_tts_webui_api.main:app"

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Already running: pid=$OLD_PID"
    echo "Log: $LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

nohup uv run uvicorn "$APP" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
PID="$!"
echo "$PID" > "$PID_FILE"

sleep 1
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Failed to start. See log: $LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi

echo "Started dots-tts-webui-api"
echo "PID: $PID"
echo "URL: http://$HOST:$PORT"
echo "Log: $LOG_FILE"
