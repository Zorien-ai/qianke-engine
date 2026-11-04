#!/usr/bin/env bash
# 定时备份（cron）
# crontab: 0 2 * * * /path/to/rag-demo/scripts/backup_control_plane.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
.venv/bin/python scripts/backup_control_plane.py --keep 7 >> logs/backup.log 2>&1
