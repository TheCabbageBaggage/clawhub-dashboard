#!/bin/bash
# ClawHub Dashboard Auto-Update Script
# Runs every 6 hours via cron

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/update.log"
LOCK_FILE="/tmp/clawhub-dashboard-update.lock"

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Update already running, skipping" >> "$LOG_FILE"
    exit 0
fi

touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

cd "$SCRIPT_DIR" || exit 1

log "=== Starting Dashboard Update ==="

# Fetch latest changes from origin
log "Fetching from origin..."
git fetch origin main 2>&1

# Check if there are new commits
LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main 2>/dev/null || echo "$LOCAL_COMMIT")

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    log "No new commits. Local: ${LOCAL_COMMIT:0:8}, Remote: ${REMOTE_COMMIT:0:8}"
    log "=== Update complete (no changes) ==="
    exit 0
fi

log "New commits found!"
log "Local:  ${LOCAL_COMMIT:0:8}"
log "Remote: ${REMOTE_COMMIT:0:8}"

# Pull changes
log "Pulling latest changes..."
git pull origin main 2>&1

# Rebuild and restart
log "Rebuilding Docker image..."
docker compose down 2>&1 || true
docker compose build --no-cache 2>&1

log "Starting updated container..."
docker compose up -d 2>&1

# Wait and verify
sleep 5
if docker compose ps | grep -q "healthy\|Up"; then
    log "✅ Dashboard updated and running successfully"
else
    log "⚠️  Container status unclear, check manually"
fi

log "=== Update complete ==="
log ""
