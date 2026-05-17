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
#   SUPERCHAT_PYTHON     指定 Python 可执行文件（否则自动探测）
#   SUPERCHAT_RUNTIME_DIR / SUPERCHAT_DATA_DIR
#     桌面版 DMG 使用：脚本与 monitor_tip.py 在只读 RUNTIME_DIR；
#     venv、streamers.json、日志、pid 在可写 DATA_DIR（需同时设置两者）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://localhost:17865"
PORT="17865"

if [[ -n "${SUPERCHAT_RUNTIME_DIR:-}" && -n "${SUPERCHAT_DATA_DIR:-}" ]]; then
  RUNTIME_DIR="$(cd "$SUPERCHAT_RUNTIME_DIR" && pwd)"
  DATA_DIR="$(cd "$SUPERCHAT_DATA_DIR" && pwd)"
  APP_DIR="$DATA_DIR"
  ENTRY="$RUNTIME_DIR/monitor_tip.py"
  PID_FILE="$DATA_DIR/superchat-monitor.pid"
  LOG_FILE="$DATA_DIR/superchat-monitor.log"
else
  APP_DIR="$SCRIPT_DIR"
  ENTRY="$APP_DIR/monitor_tip.py"
  PID_FILE="$APP_DIR/superchat-monitor.pid"
  LOG_FILE="$APP_DIR/superchat-monitor.log"
fi

resolve_python() {
  if [[ -n "${SUPERCHAT_PYTHON:-}" ]]; then
    printf '%s\n' "$SUPERCHAT_PYTHON"
    return
  fi
  local uv_venv_python="$APP_DIR/.venv/bin/python"
  if [[ -x "$uv_venv_python" ]]; then
    printf '%s\n' "$uv_venv_python"
    return
  fi
  echo "未找到项目 Python：请先在项目目录执行 uv sync，或设置 SUPERCHAT_PYTHON" >&2
  exit 1
}

read_pid() {
  cat "$PID_FILE" 2>/dev/null || true
}

cleanup_pid_file() {
  rm -f "$PID_FILE"
}

pid_exists() {
  local pid="$1"
  if lsof -p "$pid" >/dev/null 2>&1; then
    return 0
  fi
  ps -p "$pid" >/dev/null 2>&1
}

pid_belongs_to_monitor() {
  local pid="$1"
  local cmdline
  cmdline="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
  [[ -n "$cmdline" ]] || return 1
  # 优先：精确匹配本项目入口绝对路径（由 cmd_start 启动时使用）
  if [[ "$cmdline" == *"$ENTRY"* ]]; then
    return 0
  fi
  # 兼容：手动在项目目录执行 `python monitor_tip.py`（相对路径）
  if [[ "$cmdline" == *"monitor_tip.py"* && "$cmdline" == *"superchat-monitor"* ]]; then
    return 0
  fi
  return 1
}

pid_is_python_listener_on_port() {
  local pid="$1"
  local proc_name
  proc_name="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk -v p="$pid" '$2==p {print $1; exit}')"
  [[ "$proc_name" == python* ]]
}

pid_looks_like_monitor() {
  local pid="$1"
  if pid_belongs_to_monitor "$pid"; then
    return 0
  fi
  if pid_is_python_listener_on_port "$pid"; then
    return 0
  fi
  return 1
}

discover_pid_from_port() {
  local pid
  pid="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$pid"
    return 0
  fi
  return 1
}

write_pid_file() {
  local pid
  pid="$1"
  printf '%s\n' "$pid" > "$PID_FILE"
}

wait_for_http_ready() {
  local retries=40
  while (( retries > 0 )); do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --max-time 1 "$URL" >/dev/null 2>&1; then
        return 0
      fi
    else
      if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.25
    ((retries--))
  done
  return 1
}

get_valid_pid() {
  local pid=""
  if [[ -f "$PID_FILE" ]]; then
    pid="$(read_pid)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && pid_exists "$pid" && pid_looks_like_monitor "$pid"; then
      printf '%s\n' "$pid"
      return 0
    fi
    cleanup_pid_file
  fi
  pid="$(discover_pid_from_port || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && pid_exists "$pid" && pid_looks_like_monitor "$pid"; then
    write_pid_file "$pid"
    printf '%s\n' "$pid"
    return 0
  fi
  return 1
}

is_running() {
  get_valid_pid >/dev/null 2>&1
}

cmd_status() {
  local pid
  if pid="$(get_valid_pid)"; then
    echo "运行中  pid=$pid  $URL  日志: $LOG_FILE"
    return 0
  fi
  echo "未运行"
  return 1
}

cmd_stop() {
  local pid
  if ! pid="$(get_valid_pid)"; then
    cleanup_pid_file
    echo "未运行（已清理 pid 文件）"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  sleep 1
  if pid_exists "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  cleanup_pid_file
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
    wait_for_http_ready || true
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
