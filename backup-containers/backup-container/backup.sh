#!/bin/bash
# ============================================
# Backup-Service: restic → Hetzner Storage Box
# Verschlüsselte, inkrementelle Backups
# Läuft im separaten Backup-Container
# ============================================

set -e
LOG=/var/log/backup.log
mkdir -p $(dirname $LOG)

# Konfiguration
RESTIC_REPO=/mnt/storagebox/backup/restic
RESTIC_PASSWORD_FILE=/root/.storagebox/restic_password.txt
SSH_KEY=/root/.storagebox/id_ed25519_storagebox

# Backup-Quellen (vom Host gemountet)
BACKUP_SOURCES=(
  /data/backup-sources/workspace
  /data/backup-sources/config
  /data/backup-sources/opt
)

echo "=== Backup $(date '+%Y-%m-%d %H:%M:%S') ===" >> $LOG

# Restic-Passwort
if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
  echo "FEHLER: Restic-Passwort fehlt: $RESTIC_PASSWORD_FILE" >> $LOG
  exit 1
fi
export RESTIC_PASSWORD="$(cat $RESTIC_PASSWORD_FILE)"

# Repo initialisieren falls nötig
if ! restic -r "$RESTIC_REPO" snapshots > /dev/null 2>&1; then
  echo "--- Initialisiere restic Repo ---" >> $LOG
  restic -r "$RESTIC_REPO" init >> $LOG 2>&1
fi

# Backup ausführen
echo "--- Backup starten ---" >> $LOG
restic -r "$RESTIC_REPO" backup \
  "${BACKUP_SOURCES[@]}" \
  --exclude "node_modules" \
  --exclude ".git" \
  --exclude "venv" \
  --exclude "__pycache__" \
  --exclude "*.log" \
  >> $LOG 2>&1

# Alte Snapshots aufräumen (7 tägliche, 4 wöchentliche, 6 monatliche)
echo "--- Aufräumen alter Snapshots ---" >> $LOG
restic -r "$RESTIC_REPO" forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --prune \
  >> $LOG 2>&1

echo "=== Backup abgeschlossen $(date '+%H:%M:%S') ===" >> $LOG
