# Backup & Sync Container

Separate Docker-Container für Backup- und Sync-Prozesse, die aus dem OpenClaw-Container ausgelagert wurden, um Memory-Pressure zu vermeiden.

## Container

### 1. `backup-container` — restic-Backups
- **Zweck:** Verschlüsselte, inkrementelle restic-Backups des OpenClaw-Workspace + Config + /opt auf die Hetzner Storage Box
- **Cron:** Täglich 02:00 Uhr (`backup.sh`), 03:00 Uhr (`rsync_sync.sh`)
- **Ziel:** `/mnt/storagebox/backup/restic` (restic) + `/mnt/storagebox/rsync/` (rsync)
- **Retention:** 7 tägliche, 4 wöchentliche, 6 monatliche Snapshots

### 2. `drive-sync-container` — Google Drive ↔ Storagebox
- **Zweck:** Bidirektionaler rclone-Sync zwischen Google Drive (`gdrive:`) und Storagebox (`storagebox:drive-mirror`)
- **Cron:** Alle 30 Minuten (`drive_sync.sh`)
- **Ressourcen:** ~28 MB RAM (vorher ~1.8 GB im OpenClaw-Container)

## Deployment (auf Hostinger-Host 187.124.178.155)

```bash
# Backup-Container
cd /opt/backup-container
docker compose up -d --build

# Drive-Sync-Container
cd /opt/drive-sync-container
docker compose up -d --build
```

## Volumes

Beide Container mounten:
- `/mnt/storagebox` — Hetzner Storage Box (sshfs, systemd-Mount `mnt-storagebox.mount`)
- `/opt/infra/storagebox` — Storagebox-Konfiguration (SSH-Key, Passwort)
- Logs unter `/opt/*/data/logs/`

## Secrets

- **rclone.conf** (gdrive-Token + storagebox): `/opt/drive-sync-container/config/rclone.conf` (600)
- **restic-Passwort:** `/opt/infra/storagebox/restic_password.txt` (600)
- **Storagebox-SSH-Key:** `/opt/infra/storagebox/id_ed25519_storagebox` (600)

> ⚠️ Secrets sind NICHT in diesem Repo — nur die Skripte/Konfiguration ohne Secrets.
