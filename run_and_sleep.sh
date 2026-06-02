#!/bin/bash
# Runs the cold email agent, then re-enables sleep when done.
# Before running: sudo pmset -a disablesleep 1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/logs/run_$(date +%Y%m%d_%H%M%S).log"

echo "=== Send run started at $(date) ===" | tee "$LOG"
echo "Sleep is disabled. Will re-enable when done." | tee -a "$LOG"

cd "$SCRIPT_DIR"

# caffeinate as backup layer (prevents idle sleep if pmset wasn't set)
caffeinate -dims python3 agent.py send --live --max 150 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Send run finished at $(date) ===" | tee -a "$LOG"

# Re-enable sleep
sudo pmset -a disablesleep 0
echo "Sleep re-enabled." | tee -a "$LOG"
