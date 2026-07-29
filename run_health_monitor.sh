#!/bin/bash
# Health Monitor — cron wrapper
# Runs health_monitor.py with output logging.
# Silent by default — only output on errors.

set +euo pipefail  # Don't let failures prevent logging

WORKSPACE="/data/.openclaw/workspace"
LOG_DIR="$WORKSPACE/logs"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
mkdir -p "$LOG_DIR" "$WORKSPACE/scripts/health"

# Run the monitor, capture output
cd "$WORKSPACE"
OUTPUT=$(python3 "$WORKSPACE/scripts/health/health_monitor.py" 2>&1)
EXIT_CODE=$?

# Log the full output for debugging
{
  echo "[$TIMESTAMP] Health Monitor exit=$EXIT_CODE"
  echo "$OUTPUT"
} >> "$LOG_DIR/health-monitor.log" 2>/dev/null

# Summary line for quick checking
SUMMARY=$(echo "$OUTPUT" | grep -E "(Health Monitor|Green:|Yellow:|Red:|Unfix)" | head -5)
echo "[$TIMESTAMP] $SUMMARY"

# If red (unfixable), report to stderr (caught by cron system)
if [ $EXIT_CODE -eq 2 ]; then
    echo "[$TIMESTAMP] ❌ RED: Unfixable issues requiring attention" >&2
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[$TIMESTAMP] 🟡 Yellow: Auto-remediation applied"
fi

exit $EXIT_CODE