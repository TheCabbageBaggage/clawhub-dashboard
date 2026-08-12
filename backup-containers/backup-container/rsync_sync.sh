#!/bin/bash
# ============================================
# rsync: Lokale Daten → Storage Box
# Einweg-Sync (Push) für wichtige Verzeichnisse
# ============================================

set -e
LOG=/var/log/rsync_sync.log
mkdir -p $(dirname $LOG)

echo "=== rsync Sync $(date '+%Y-%m-%d %H:%M:%S') ===" >> $LOG

# Zielverzeichnisse anlegen
mkdir -p /mnt/storagebox/rsync/workspace
mkdir -p /mnt/storagebox/rsync/opt

# Quellen → Storagebox
# --no-owner --no-group: Storagebox unterstützt kein chown
rsync -avz --delete --no-owner --no-group \
  /data/backup-sources/workspace/ \
  /mnt/storagebox/rsync/workspace/ \
  --exclude node_modules \
  --exclude .git \
  --exclude '*.log' \
  >> $LOG 2>&1

rsync -avz --delete --no-owner --no-group \
  /data/backup-sources/opt/ \
  /mnt/storagebox/rsync/opt/ \
  --exclude node_modules \
  --exclude .git \
  --exclude '*.log' \
  >> $LOG 2>&1

echo "=== rsync abgeschlossen $(date '+%H:%M:%S') ===" >> $LOG
