#!/bin/bash
# Setup cron job for dashboard auto-update
# Run this on the host where docker is available

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SCRIPT="${SCRIPT_DIR}/update-dashboard.sh"

# Add to crontab
echo "Setting up cron job..."
(crontab -l 2>/dev/null | grep -v "clawhub-dashboard/update-dashboard.sh"; echo "0 */6 * * * ${UPDATE_SCRIPT} >> ${SCRIPT_DIR}/cron.log 2>&1") | crontab -

echo "Cron job installed. Running every 6 hours."
echo "Current crontab:"
crontab -l | grep clawhub-dashboard
