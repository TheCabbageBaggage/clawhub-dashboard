# ClawHub Dashboard — Docker Deployment

## Quick Start

```bash
# 1. Build and start
docker compose up -d --build

# 2. Verify running
docker compose ps
curl http://localhost:3001/api/data

# 3. Setup auto-update cron
./setup-cron.sh
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User          │────▶│  Nginx (Host)    │────▶│  Dashboard      │
│   (Browser)     │     │  Port 80/443     │     │  Container      │
│                 │     │  dashboard.claw..│     │  Port 3001      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Reverse Proxy   │
                        │  location /      │
                        │  proxy_pass      │
                        │  localhost:3001  │
                        └──────────────────┘
```

## Configuration

### Nginx (auf Host)
Das Dashboard läuft als Docker Container auf Port 3001 (localhost only).
Nginx auf dem Host reverse-proxied zu diesem Port:

```nginx
location / {
    proxy_pass http://localhost:3001/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 3001 | Server port |
| `NODE_ENV` | production | Node environment |

## Auto-Update

Das `update-dashboard.sh` Skript:
1. Prüft alle 6h auf neue Commits in `origin/main`
2. Bei neuen Commits: `git pull` → `docker compose build --no-cache` → `docker compose up -d`
3. Loggt Ergebnis nach `update.log`

Manuell ausführen:
```bash
./update-dashboard.sh
```

## Logs

```bash
# Container logs
docker compose logs -f

# Update logs
tail -f update.log

# Cron logs
tail -f cron.log
```

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Port 3001 belegt | `lsof -i :3001` → Prozess killen oder Port ändern |
| Nginx can't reach container | Prüfe `docker compose ps` — Container muss "healthy" zeigen |
| Git pull failed | Manuell `git status` prüfen, evtl. conflicts resolven |
| Update loop | `update.log` prüfen auf Fehler |

## Files

- `docker-compose.yml` — Container definition
- `Dockerfile` — Image build
- `update-dashboard.sh` — Auto-update logic
- `setup-cron.sh` — Cron installation
