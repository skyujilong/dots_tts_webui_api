#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PID_FILE="$ROOT_DIR/.data/server.pid"
APP_PATTERN="uvicorn dots_tts_webui_api.main:app"
STOPPED=0

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  echo "Stopping pid=$pid"
  kill "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      STOPPED=1
      return 0
    fi
    sleep 0.2
  done
  echo "Force killing pid=$pid"
  kill -9 "$pid" 2>/dev/null || true
  STOPPED=1
}

if [[ -f "$PID_FILE" ]]; then
  stop_pid "$(cat "$PID_FILE")"
  rm -f "$PID_FILE"
fi

PIDS="$(pgrep -f "$APP_PATTERN" || true)"
if [[ -n "$PIDS" ]]; then
  while IFS= read -r pid; do
    [[ "$pid" == "$$" ]] && continue
    stop_pid "$pid"
  done <<< "$PIDS"
fi

if [[ "$STOPPED" -eq 1 ]]; then
  echo "Stopped dots-tts-webui-api"
else
  echo "No running dots-tts-webui-api process found"
fi
