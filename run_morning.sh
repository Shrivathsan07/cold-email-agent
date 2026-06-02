#!/bin/bash
# One-shot morning send — runs at 7am, sends all pending, then cleans itself up

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/logs/morning_$(date +%Y%m%d_%H%M%S).log"

echo "=== Morning send started at $(date) ===" >> "$LOG"

# Wait 60s after wake to let network connect
sleep 60

cd "$SCRIPT_DIR"
python3 agent.py send --live --max 150 >> "$LOG" 2>&1

echo "=== Morning send finished at $(date) ===" >> "$LOG"

# Clean up: unload the launchd job so it doesn't run again
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.coldmail.morningsend.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.coldmail.morningsend.plist

# Cancel the scheduled wake
sudo pmset schedule cancelall 2>/dev/null

echo "=== Cleanup done ===" >> "$LOG"
