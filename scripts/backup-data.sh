#!/bin/zsh
# 每日备份：把 data/ 中补不回来的部分复制到 IROS_BACKUP_DIR（项目根目录 .env 中设置，不入库），
# 例如 Google Drive 桌面版同步的文件夹，由它上传到云端。
#
# 备份：每日快照与取得记录（data/raw、data/normalized、data/catalog）、SEC 财报的分区与目录。
# 不备份：SEC 季度数据集原始 ZIP（data/edgar/raw/fsds，约 5 GB），可以重新下载。
# 只增加和更新，不删除目标中的文件：本机误删不会连带删除备份。
# 目标不可用（未设置、云盘未运行或账号断开）时跳过并说明，退出码 0，不影响当天的数据取得。
set -uo pipefail

ROOT="${IROS_ROOT:-${0:A:h:h}}"  # IROS_ROOT 只用于测试
if [[ -z "${IROS_BACKUP_DIR:-}" && -f "$ROOT/.env" ]]; then
  IROS_BACKUP_DIR="$(sed -n 's/^IROS_BACKUP_DIR=//p' "$ROOT/.env" | tail -1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
fi
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if [[ -z "${IROS_BACKUP_DIR:-}" ]]; then
  echo "[$(stamp)] 备份跳过：未设置 IROS_BACKUP_DIR"
  exit 0
fi
parent="${IROS_BACKUP_DIR:h}"
if [[ ! -d "$parent" ]]; then
  echo "[$(stamp)] 备份跳过：$parent 不存在（云盘未运行或账号已断开？）"
  exit 0
fi
dest="$IROS_BACKUP_DIR/data"
mkdir -p "$dest" || { echo "[$(stamp)] 备份失败：无法创建 $dest"; exit 1; }

# -rt：递归并保留修改时间（云盘文件夹不支持权限与扩展属性，所以不用 -a）；不加 --delete
rsync -rt --exclude 'edgar/raw/fsds/' "$ROOT/data/" "$dest/"
code=$?
if (( code == 0 )); then
  echo "[$(stamp)] 备份完成：$(du -sh "$dest" | cut -f1) → $dest"
else
  # launchd 后台任务通常无权写入 ~/Library/CloudStorage（macOS 隐私保护），交互运行却正常
  echo "[$(stamp)] 备份失败：rsync 退出码 $code（目标为 $dest）"
  exit 1
fi
