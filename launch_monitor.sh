#!/bin/bash

set -euo pipefail

APP_DIR="/Users/chandyoung/Projects.localized/superchat-monitor"
PYENV_PY="$HOME/.pyenv/versions/chat-site-tracking/bin/python"
ENTRY="$APP_DIR/monitor_tip.py"
PID_FILE="$APP_DIR/superchat-monitor.pid"
URL="http://127.0.0.1:17865"
LOG_FILE="$APP_DIR/superchat-monitor.log"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" >/dev/null 2>&1
}

kill_existing() {
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    kill "$pid" >/dev/null 2>&1 && sleep 1 || true
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
}

prompt_buttons() {
  local message="$1"
  local button1="$2"
  local button2="$3"
  local default_btn="${4:-1}"
  /usr/bin/osascript <<OSA
display dialog "$message" buttons {$button1,$button2} default button $default_btn giving up after 0
OSA
}

if is_running; then
  result=$(prompt_buttons "SuperChat Monitor 已在运行：$URL" "\"退出进程\"" "\"继续运行\"" 2)
  if [[ "$result" == *"退出进程"* ]]; then
    kill_existing
    /usr/bin/osascript -e 'display notification "已停止 SuperChat Monitor" with title "SuperChat Monitor"'
  fi
  exit 0
fi

cd "$APP_DIR"
nohup "$PYENV_PY" "$ENTRY" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

result=$(prompt_buttons "SuperChat Monitor 已启动：$URL" "\"后台运行\"" "\"退出进程\"" 1)
if [[ "$result" == *"退出进程"* ]]; then
  kill_existing
  /usr/bin/osascript -e 'display notification "已退出 SuperChat Monitor" with title "SuperChat Monitor"'
else
  /usr/bin/osascript -e "display notification \"后台运行中：$URL\" with title \"SuperChat Monitor\""
fi
