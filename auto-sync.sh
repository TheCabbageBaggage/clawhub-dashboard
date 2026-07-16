#!/bin/bash
# Auto-sync dashboard changes to GitHub every 15 minutes
cd /var/www/dashboard
git config --global --add safe.directory /var/www/dashboard 2>/dev/null

# Only commit if there are changes
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    git add -A
    git commit -m "auto: dashboard sync $(date '+%Y-%m-%d %H:%M')" 2>/dev/null
    git push origin master 2>&1
fi
