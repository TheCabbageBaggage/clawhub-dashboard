#!/bin/bash
# Health Dashboard Server
# Starts the health dashboard HTTP server.
# Usage: ./serve_dashboard.sh [port]

set -euo pipefail

PORT="${1:-18900}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "📊 Clowie Health Dashboard"
echo "   Serving: $DIR/health_dashboard.html"
echo "   URL:     http://localhost:$PORT"
echo "   PID:     $$"
echo ""

exec python3 "$DIR/serve_dashboard.py" "$PORT"