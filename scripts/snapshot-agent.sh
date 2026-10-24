#!/bin/zsh
# 本机定时快照（macOS launchd）：每个工作日 19:45（本机时间）先运行 `iros fetch --all`，
# 取得 config/datasets.yaml 中登记了 scheduled_fetch 的数据集；再运行 `iros edgar sync`，
# 检查 SEC 财报（FSDS 季度文件只发 HEAD，变化时才下载；Company Facts 逐家取得）。都存入本地 data/。
# 两步互不影响；任一步失败时任务的退出码不为 0。
#
# Treasury 与 FRED 只提供当前修订版本，时点研究只能依靠当时已取得的快照；漏掉的日期补不回来。
# 电脑睡眠时错过的运行会在唤醒后补跑；关机时错过的运行不会补。
#
#   scripts/snapshot-agent.sh install     安装或更新并启用
#   scripts/snapshot-agent.sh uninstall   停用并移除
#   scripts/snapshot-agent.sh status      是否已加载，以及最近的日志
#   scripts/snapshot-agent.sh run         立即运行一次（经 launchd，与定时运行相同的环境）
set -euo pipefail

LABEL="com.investment-research-os.snapshots"
ROOT="${0:A:h:h}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/investment-research-os"
LOG="$LOG_DIR/snapshots.log"
DOMAIN="gui/$(id -u)"

install_agent() {
  local uv
  uv="$(command -v uv)" || { echo "找不到 uv；请先安装 uv" >&2; exit 1; }
  mkdir -p "$LOG_DIR" "${PLIST:h}"
  local days=""
  for d in 1 2 3 4 5; do
    days+="    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>45</integer></dict>
"
  done
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string><string>-c</string>
    <string>s=0; "$uv" run --project "$ROOT" iros --root "$ROOT" fetch --all || s=1; "$uv" run --project "$ROOT" iros --root "$ROOT" edgar sync || s=1; exit \$s</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <array>
$days  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
  plutil -lint "$PLIST" >/dev/null
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "已安装：$PLIST"
  echo "日志：$LOG"
}

case "${1:-}" in
  install) install_agent ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "已移除 $LABEL（日志保留在 $LOG）" ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | grep -E "state|last exit code|runs" || true
    else
      echo "$LABEL 未加载"
    fi
    [[ -f "$LOG" ]] && { echo "--- 最近日志 ---"; tail -n 20 "$LOG"; } || true ;;
  run) launchctl kickstart -p "$DOMAIN/$LABEL" ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
