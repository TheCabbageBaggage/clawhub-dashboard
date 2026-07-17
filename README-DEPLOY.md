# ClawHub Dashboard — Traefik Deployment

## Architecture

```
Internet → Traefik (Docker) → clawhub-dashboard:3001
                │
                ├── TLS (Let's Encrypt)
                ├── HTTP→HTTPS redirect
                └── Router: dashboard.claw.lkohl.duckdns.org
```

## Prerequisites

- **Traefik** running as Docker container with:
  - Let's Encrypt certificate resolver configured
  - `web` (port 80) and `websecure` (port 443) entrypoints
  - Docker provider enabled
- **Docker** and **docker compose** on the host
- **Git** access to `github.com/TheCabbageBaggage/clawhub-dashboard`

## Quick Deploy

```bash
# 1. Clone into workspace
cd /data/.openclaw/workspace
git clone git@github.com:TheCabbageBaggage/clawhub-dashboard.git
cd clawhub-dashboard

# 2. Verify Traefik network name
docker network ls | grep traefik
# Expected: traefik_default, traefik, or traefik-traefik-1
# If different, update docker-compose.yml networks.traefik-net.name

# 3. Deploy
docker compose up -d --build

# 4. Setup auto-update cron (every 6h)
./setup-cron.sh

# 5. Verify
curl http://localhost:3001/api/data
curl https://dashboard.claw.lkohl.duckdns.org/api/data
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Traefik-routed container with labels |
| `Dockerfile` | Node.js 20 Alpine build |
| `update-dashboard.sh` | Git pull → rebuild → restart |
| `setup-cron.sh` | Install 6h cron job |
| `dashboard/server.js` | HTTP server on port 3001 |

## Traefik Labels

The container self-registers with Traefik via Docker labels:

| Label | Value |
|-------|-------|
| `traefik.enable` | `true` |
| Router (HTTP) | `dashboard.claw.lkohl.duckdns.org` → redirect to HTTPS |
| Router (HTTPS) | `dashboard.claw.lkohl.duckdns.org` → port 3001 |
| TLS | Let's Encrypt via `certresolver=letsencrypt` |

## Troubleshooting

### Traefik network not found
```bash
# List networks
docker network ls

# If Traefik network has a different name, update docker-compose.yml:
#   networks.traefik-net.name: <actual-name>

# Or create the network if Traefik uses a different one:
docker network create traefik-net
docker network connect traefik-net <traefik-container>
```

### Container not reachable via Traefik
```bash
# Check Traefik dashboard (if enabled)
curl http://localhost:8080/api/rawdata | jq '.routers'

# Check container is on the right network
docker inspect clawhub-dashboard | jq '.[0].NetworkSettings.Networks'

# Check Traefik logs
docker logs <traefik-container> --tail 50
```

### Domain not resolving
```bash
# Verify DNS
dig dashboard.claw.lkohl.duckdns.org

# DuckDNS update (if using DuckDNS)
curl "https://www.duckdns.org/update?domains=claw.lkohl&token=<token>&ip="
```
