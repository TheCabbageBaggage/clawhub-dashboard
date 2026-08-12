#!/bin/bash
# ============================================
# Google Drive ↔ Hetzner Storage Box Sync
# Bidirektionaler Sync via rclone
# Läuft im separaten Drive-Sync-Container
# ============================================

set -e
LOG=/var/log/drive_sync.log
mkdir -p $(dirname $LOG)

echo "=== Drive Sync $(date '+%Y-%m-%d %H:%M:%S') ===" >> $LOG

# Bidirektionaler Sync: Drive → Storage Box (Download)
echo "--- Sync Drive → Storage Box ---" >> $LOG
rclone sync gdrive: storagebox:drive-mirror \
  --progress \
  --transfers 1 \
  --checkers 4 \
  --log-file $LOG 2>&1 | tail -5 >> $LOG

# Bidirektionaler Sync: Storage Box → Drive (Upload lokaler Änderungen)
echo "--- Sync Storage Box → Drive ---" >> $LOG
rclone sync storagebox:drive-mirror gdrive: \
  --progress \
  --transfers 1 \
  --checkers 4 \
  --log-file $LOG 2>&1 | tail -5 >> $LOG

echo "=== Sync abgeschlossen $(date '+%H:%M:%S') ===" >> $LOG
