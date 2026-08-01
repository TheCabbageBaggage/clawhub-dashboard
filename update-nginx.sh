#!/bin/bash
# Simple update script for nginx-based clawhub-dashboard
cd /var/www/dashboard

# Pull latest
git fetch origin master
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date)] Updating: ${LOCAL:0:8} → ${REMOTE:0:8}"
    git reset --hard origin/master
    
    # Restart node server
    pkill -f 'node dashboard/server.js' 2>/dev/null || true
    sleep 1
    PORT=8080 DASHBOARD_PASSWORD=clawhub nohup node dashboard/server.js > /tmp/dashboard.log 2>&1 &
    echo "[$(date)] Server restarted"
else
    echo "[$(date)] No changes"
fi
