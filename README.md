# KimKom-CommandCenter

Central control plane for KimKom agency. Dev environments, monitoring, error tracking, deployment tools.

## Server
- CommandCenter: 192.168.178.19 / 100.67.52.95 (Tailscale)
- TEST VM: 192.168.178.20 / 100.114.91.105 (Tailscale)

## Services
- Traefik — routes *.kimkom.net to dev instances
- PostgreSQL 17 — shared database for all dev instances
- Portainer CE — container management (Tailscale:9000)
- Grafana — dashboards (Tailscale:3000)
- Prometheus + Alertmanager — monitoring and alerts
- GlitchTip — error tracking (Tailscale:8001)
- Loki + Promtail — log aggregation

## Quick Commands
docker compose -p odoo-dev --env-file .env up -d                    # start core
docker compose -f monitoring/docker-compose.yml --env-file .env up -d  # start monitoring
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d  # start GlitchTip
./scripts/create-odoo-instance.sh --client <name>                   # new dev instance

## Production
Deployed from /opt/KimKom-stack. Each customer gets their own server with the full stack.
