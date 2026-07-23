# KimKom-CommandCenter

Central control plane for the KimKom agency. Hosts dev environments for all clients, monitoring, error tracking, and deployment tools.

## What This Server Is

- **Name**: KimKom-CommandCenter (Proxmox VM at 192.168.178.19)
- **Tailscale**: `100.67.52.95` for management services
- **Purpose**: Development environment + control plane for all client PROD servers
- **Clients**: SuperTCG, Vranckeneers (and future clients)

## Services on This Server

### Core Infrastructure
- **PostgreSQL 17** — Shared database for all dev Odoo instances
- **Traefik** — Routes `*.kimkom.net` to dev Odoo containers
- **Portainer CE** — Container management (port 9000)

### Monitoring & Observability
- **Grafana + Prometheus** — Central dashboards and alerting
- **GlitchTip** — Error tracking for all Odoo instances

### Dev Environments (per client)
- **SuperTCG** — `https://supertcg.kimkom.net`
- **Vranckeneers** — `https://vranckeneers.kimkom.net`

## Directory Layout

```
/opt/kimkom-commandcenter/
  docker-compose.yml          # PostgreSQL 17 + Portainer CE
  .env                        # Core secrets
  instances/
    SuperTCG/                 # Dev Odoo instance
    vranckeneers/             # Dev Odoo instance
  monitoring/                 # Grafana + Prometheus
  glitchtip/                  # Error tracking
  scripts/                    # Deployment scripts
  rclone/                     # S3 backup configs
  ssh/                        # Deploy keys
```

## KimKom-Stack (PROD Servers)

Separate GitHub repo deployed to each client's Hetzner server:
- **Repo**: https://github.com/Alex12358795/KimKom-stack
- **Core services**: Odoo, PostgreSQL, Traefik, monitoring agents, and online backups
- **Optional profiles**: Mattermost, n8n, Vaultwarden, Metabase, and Plausible
- **Proxy**: Traefik with Let's Encrypt auto-SSL
- **Monitoring**: Prometheus exporters, Grafana, and GlitchTip
- **Backups**: Restic to KimKom S3

## Quick Commands

```bash
# Start core services
cd /opt/kimkom-commandcenter
docker compose up -d

# Start monitoring (reads GRAFANA_PASSWORD and MANAGEMENT_BIND_IP)
docker compose -f monitoring/docker-compose.yml --env-file .env up -d

# Start GlitchTip
cd /opt/kimkom-commandcenter/glitchtip
docker compose up -d

# Create new client dev instance
./scripts/create-odoo-instance.sh --client <name>

# Production deployment is managed from /opt/KimKom-stack.
```

## Network Architecture

```
Internet → Cloudflare Tunnel → Traefik (CommandCenter:80) → Dev Odoo instances
                                      ↓
                                Grafana (3000) — Tailscale only
                                GlitchTip (8001) — Tailscale only
                                Prometheus (9090) — localhost only
```

## Security Notes

- Grafana, Portainer, and GlitchTip bind to Tailscale `100.67.52.95`
- Prometheus, Alertmanager, and local exporters remain localhost-only
- GlitchTip is internal (no external domain)
- Deploy keys in `/opt/kimkom-commandcenter/ssh/` are local-only and ignored by Git
- Secrets in `.env` (never committed)
