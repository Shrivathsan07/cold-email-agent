#!/bin/bash
# Local daily run. Same thing the GitHub Action does, for when you would
# rather keep your pipeline off GitHub entirely.
#
# Schedule it with cron (Linux) or launchd (Mac):
#   crontab -e
#   0 7 * * 1-5 /path/to/cold-email-agent/run_recruiting_brief.sh
#
# On a Mac, `pmset` sleep will skip cron runs. launchd with RunAtLoad handles
# that better; see RECRUITING.md.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p logs
LOG="logs/recruiting_$(date +%Y%m%d).log"

{
  echo "=== recruiting brief $(date) ==="
  python3 -m recruit sync
  echo
  if python3 -m recruit report --email; then
    echo "brief emailed"
  else
    echo "email not configured, printing instead"
    python3 -m recruit report
  fi
  echo "=== done $(date) ==="
} 2>&1 | tee -a "$LOG"
