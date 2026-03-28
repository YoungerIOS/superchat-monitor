#!/bin/bash
# SuperChat Monitor — 启动 / 停止 / 状态（本机长期运行用）
#
# 用法:
#   ./monitor_ctl.sh start [--open]   后台启动；--open 在 macOS 上打开浏览器
#   ./monitor_ctl.sh stop             停止
#   ./monitor_ctl.sh status           是否运行、PID、地址
#   ./monitor_ctl.sh restart [--open] 先停再起
#
# 可选环境变量:
#   SUPERCHAT_PYTHON  指定 Python 可执行文件（否则自动探测）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR"
ENTRY="$APP_DIR/monitor_tip.py"
PID_FILE="$APP_DIR/superchat-monitor.pid"
LOG_FILE="$APP_DIR/superchat-monitor.log"
URL="http://127.0.0.1:17865"

resolve_python() {
  if [[ -n "${SUPERCHAT_PYTHON:-}" ]]; then
    printf '%s\n' "$SUPERCHAT_PYTHON"
    return
  fi
  local pyenv_candidate="$HOME/.pyenv/versions/chat-site-tracking/bin/python"
  if [[ -x "$pyenv_candidate" ]]; then
    printf '%s\n' "$pyenv_candidate"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  echo "未找到 Python：请安装 python3 或设置环境变量 SUPERCHAT_PYTHON" >&2
  exit 1
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" >/dev/null 2>&1
}

cmd_status() {
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    echo "运行中  pid=$pid  $URL  日志: $LOG_FILE"
    return 0
  fi
  echo "未运行"
  return 1
}

cmd_stop() {
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! ps -p "$pid" >/dev/null 2>&1; then
    rm -f "$PID_FILE"
    echo "未运行（已清理 pid 文件）"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  sleep 1
  if ps -p "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "已停止"
}

cmd_start() {
  local open_browser=0
  for a in "$@"; do
    if [[ "$a" == "--open" ]]; then open_browser=1; fi
  done

  if is_running; then
    echo "已在运行: $URL（pid $(cat "$PID_FILE")）"
    if [[ "$open_browser" -eq 1 ]] && [[ "$(uname -s)" == "Darwin" ]]; then
      /usr/bin/open "$URL"
    fi
    return 0
  fi

  local py
  py="$(resolve_python)"
  cd "$APP_DIR"
  nohup "$py" "$ENTRY" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  echo "已启动  pid=$(cat "$PID_FILE")  $URL  日志: $LOG_FILE"

  if [[ "$open_browser" -eq 1 ]] && [[ "$(uname -s)" == "Darwin" ]]; then
    sleep 0.5
    /usr/bin/open "$URL"
  fi
}

cmd_restart() {
  cmd_stop || true
  cmd_start "$@"
}

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    start)    cmd_start "$@" ;;
    stop)     cmd_stop ;;
    status)   cmd_status ;;
    restart)  cmd_restart "$@" ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      echo "未知命令: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
