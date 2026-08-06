# KimKom-CommandCenter

Central control plane for KimKom agency. Dev environments, monitoring, error tracking, deployment tools.

## Server
- CommandCenter: 192.168.178.19 / 100.67.52.95 (Tailscale)
- PROD: 192.168.178.20 / 100.114.91.105 (Tailscale) — hosts the kimkom.be production stack at /opt/kimkom

## Services
- Traefik — routes *.kimkom.net to dev instances
- PostgreSQL 17 — shared database for all dev instances
- Portainer CE — container management (Tailscale:9000)
- Grafana — dashboards (Tailscale:3000)
- Prometheus + Alertmanager — monitoring and alerts
- GlitchTip — error tracking (Tailscale:8001)
- Loki + Promtail — log aggregation
- SOP — speech-to-text assistant (sop.kimkom.net, dev; SQLite, NOT backed up)
- Odoo MCP / GlitchTip MCP — MCP integration configs ( /opt/odoo-mcp, /opt/glitchtip-mcp )

## Quick Commands
docker compose -p odoo-dev --env-file .env up -d                    # start core
docker compose -f monitoring/docker-compose.yml --env-file .env up -d  # start monitoring
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d  # start GlitchTip
./scripts/01-create-odoo-instance.sh --client <name>                 # new dev instance

## Production
Deployed from /opt/kimkom-deploy. Each customer gets their own server with the full stack.
KimKom's own production: kimkom.be on PROD (100.114.91.105), tunnel-mode HTTP-only origin behind a Cloudflare tunnel, local Restic backup. New onboarding: `02-install-stack.sh` in /opt/kimkom-deploy (guided; engine is init-client.sh).
