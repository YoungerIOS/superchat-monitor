#!/bin/bash
# 图形化快捷方式：双击或通过 Automator 调用；等价于命令行请用 monitor_ctl.sh

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTL="$DIR/monitor_ctl.sh"
URL="http://127.0.0.1:17865"

chmod +x "$CTL" 2>/dev/null || true

prompt_buttons() {
  local message="$1"
  local button1="$2"
  local button2="$3"
  local default_btn="${4:-1}"
  /usr/bin/osascript <<OSA
display dialog "$message" buttons {$button1,$button2} default button $default_btn giving up after 0
OSA
}

if bash "$CTL" status >/dev/null 2>&1; then
  result=$(prompt_buttons "SuperChat Monitor 已在运行：$URL" "\"打开页面\"" "\"停止进程\"" 1)
  if [[ "$result" == *"停止进程"* ]]; then
    bash "$CTL" stop
    /usr/bin/osascript -e 'display notification "已停止 SuperChat Monitor" with title "SuperChat Monitor"'
  else
    /usr/bin/open "$URL"
  fi
  exit 0
fi

bash "$CTL" start --open
/usr/bin/osascript -e "display notification \"已启动：$URL\" with title \"SuperChat Monitor\""
