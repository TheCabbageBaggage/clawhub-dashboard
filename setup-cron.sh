#!/bin/bash
# Setup cron job for dashboard auto-update
# Run this on the host where docker is available

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SCRIPT="${SCRIPT_DIR}/update-dashboard.sh"

# Make sure the update script is executable
chmod +x "$UPDATE_SCRIPT"

# Add to crontab (every 6 hours)
echo "Setting up cron job for clawhub-dashboard auto-update..."
(crontab -l 2>/dev/null | grep -v "clawhub-dashboard/update-dashboard.sh"; echo "0 */6 * * * ${UPDATE_SCRIPT} >> ${SCRIPT_DIR}/cron.log 2>&1") | crontab -

echo ""
echo "✅ Cron job installed. Dashboard auto-update runs every 6 hours."
echo ""
echo "Current crontab entries for dashboard:"
crontab -l 2>/dev/null | grep clawhub-dashboard || echo "(none yet — will appear on next run)"
echo ""
echo "To verify Traefik network before first deploy, run:"
echo "  docker network ls | grep traefik"
echo "  # If network name differs from 'traefik-net', update docker-compose.yml"
