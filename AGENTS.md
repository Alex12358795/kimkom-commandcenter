# KimKom-CommandCenter — Agent Guide

Central control plane for KimKom agency. Dev environments, monitoring, error tracking, and deployment tools for all clients.

**Server**: Proxmox VM at 192.168.178.19
**Tailscale**: 100.67.52.95 (DNS and subnet routes disabled)
**Clients**: SuperTCG, Vranckeneers
**Repo**: https://github.com/Alex12358795/KimKom-stack (PROD stack, separate repo)

## Directory Layout

```
/opt/kimkom-commandcenter/
  docker-compose.yml          # PostgreSQL 17 + Portainer CE (shared)
  .env                        # Core secrets (POSTGRES_PASSWORD, GITHUB_TOKEN, etc.)
  instances/
    <client>/
      docker-compose.yml      # Odoo 18 container (builds from Dockerfile)
      config/odoo.conf        # db_name, db_host=odoo-postgres, addons_path
      .env                    # DB_PASSWORD, ODOO_ADMIN_PASSWORD
      addons/                 # custom modules (git tracked)
      addons-enterprise/      # Odoo Enterprise (not git tracked)
      addons-oca/             # OCA community (not git tracked)
      data/                   # filestore volume — chown 100:101
  monitoring/
    docker-compose.yml        # Prometheus + Grafana + Alertmanager + exporters
    grafana/data/             # chown 472:472
  glitchtip/
    docker-compose.yml        # Error tracking (LAN-accessible :8001)
    .env                      # POSTGRES_PASSWORD, SECRET_KEY
  scripts/
    create-odoo-instance.sh   # scaffold new client + DB + MCP config
    deploy-module.sh          # rsync modules to PROD (deprecated, use git-based)
  rclone/
    rclone.conf               # Hetzner S3 remotes (secrets, not committed)
    clients.json              # client→bucket mapping
  ssh/
    deploy_key                # SSH key for PROD servers
    deploy_key.pub
```

## Key Commands

```bash
# Start core services (PostgreSQL 17 + Portainer CE)
cd /opt/kimkom-commandcenter && docker compose up -d

# Start monitoring (Grafana + Prometheus + Alertmanager)
docker compose -f monitoring/docker-compose.yml --env-file .env up -d

# Start GlitchTip (error tracking, LAN-accessible)
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d

# Create new client dev instance
./scripts/create-odoo-instance.sh --client <name>

# Restart all dev instances
for dir in /opt/kimkom-commandcenter/instances/*/; do
    docker compose -f "$dir/docker-compose.yml" --env-file "$dir/.env" restart
done
```

## Critical Rules

### Docker Compose — ALWAYS use --env-file
Every dev instance has its own `.env` with `DB_PASSWORD`. Without `--env-file`, Odoo can't connect to PostgreSQL.

```bash
# WRONG — won't find DB_PASSWORD
docker compose -f instances/SuperTCG/docker-compose.yml up -d

# CORRECT
docker compose -f instances/SuperTCG/docker-compose.yml --env-file instances/SuperTCG/.env up -d
```

### Permissions
- Odoo data dirs: `sudo chown -R 100:101 instances/<client>/data` (Odoo runs as UID 100)
- Grafana data dir: `sudo chown -R 472:472 monitoring/grafana/data`

### PostgreSQL 17
- Shared instance for all dev Odoo databases, port 5432 (127.0.0.1 only)
- **Production backups require PG17** (dump format v1.16). Do not use PG16.
- Access: `docker exec -it odoo-postgres psql -U odoo -d odoomaster`

### GlitchTip
- Internal only: `http://100.67.52.95:8001` (Tailscale, no external domain)
- DSNs stored in `glitchtip/dsns.json` — referenced by `init-client.sh`
- Odoo integration via OCA `sentry` module (`odoo/modules/oca/sentry/` in KimKom-stack)
- **sentry module reads DSN from odoo.conf**, not from Odoo system parameters — DSN injected via `entrypoint.sh` replacing `__GLITCHTIP_DSN__` placeholder
- sentry-sdk pip package required (in Dockerfile), manifest constraint relaxed from `<=2.22.0` to `>=2.0.0` (commit `bf1816e`)
- Module install: `docker compose run --rm odoo -- -i sentry --stop-after-init --no-http` (one-time per deployment)
- Sentry auto-initializes on subsequent Odoo starts via `post_load` hook

### Portainer
- **CE on CommandCenter**: `http://100.67.52.95:9000`, admin password in `.env`
- **Agent on PROD servers**: MUST use `ports: "9001:9001"` (NOT `expose: 9001`) — `expose` only works within Docker network, `ports` exposes to host
- Agent uses TLS by default (`use_tls=true`), Portainer API requires `TLS:true, TLSSkipVerify:true`
- Portainer CE 2.39.3 API may reject programmatic endpoint creation — add manually via UI: Environments → Add → Docker Agent → IP:9001
- UFW on PROD should allow port 9001 only from the CommandCenter Tailscale address.
- PROD Portainer (port 9000) requires initial browser setup even with `--force` flag

## KimKom-Stack (PROD Deployment)

Separate GitHub repo deployed to each client's Hetzner server. Key scripts:
- `init-client.sh` — full provisioning (Docker + clone + deploy + hardening)
- `update.sh` — git pull + smart restart (only changed services)
- `backup.sh` — Restic backups to KimKom S3

**Security hardening** (since commit `a177773`):
- UFW firewall (22/80/443 only)
- SSH password auth disabled + fail2ban
- Traefik dashboard basic auth (raw `$` in hash, NOT `$$`)
- Rate limiting (100 req/min)
- Management agents and exporters restricted to Tailscale addresses

**Recent commits** (bb0b812 → bf1816e):
- OCA sentry module added to `odoo/modules/oca/sentry/`
- Portainer Agent changed from `expose` to `ports`
- redirect-to-https middleware fixed: `@docker` → `@file`

## DNS & SSL Gotchas

**Local testing behind NPM** (home network):
- Traefik must be HTTP-only (no Let's Encrypt)
- Remove `redirect-to-https` middleware from all services
- Use `docker-compose.local.yml` override
- NPM forwards to `http://<server>:80` (HTTP, not HTTPS)

**Production (Hetzner with public IP)**:
- Traefik auto-provisions Let's Encrypt SSL certs
- DNS must have A records for base domain AND all subdomains (or wildcard `*.domain`)
- Port 80 must be free for Let's Encrypt HTTP-01 challenge

**Dynamic DNS (kimkom.be)**:
- OVH DynHost only updates existing A records — cannot create them
- Create A record first, then DynHost entry for same subdomain
- Router update URL: `https://[USER]:[PASS]@www.ovh.com/nic/update?system=dyndns&hostname=[DOMAIN]&myip=[IP]`

## Common Mistakes

- **Port 80 conflict**: Old Coolify proxy or other service using port 80 prevents Traefik from binding. Check: `docker ps | grep 80->80`
- **503 errors**: inspect the instance's `odoo-proxy` attachment and Traefik service labels.
- **SSL errors on subdomains**: DNS records missing. Check `nslookup <subdomain>.<domain>`
- **Dashboard auth 401**: Auth file uses `$$` instead of `$` in hash. Must be raw `$apr1$...` format
- **init-client.sh fails**: Ensure `LETSENCRYPT_EMAIL` is set in `.env` and DNS resolves before running
- **sentry_dsn sed failure**: DSN contains `/` which breaks sed if using `/` delimiter. Use `|` delimiter: `s|__GLITCHTIP_DSN__|${DSN}|g`
- **Module dirs root-owned**: `odoo/modules/{client,enterprise,oca}/` created by Docker may be root-owned, blocking `git pull`. Fix: `sudo chown -R alex:alex odoo/modules/`
- **sentry-sdk version**: OCA manifest constrains `<=2.22.0` but pip installs 2.63.0. Relaxed to `>=2.0.0` (compatible)
- **Portainer agent expose vs ports**: `expose: 9001` is Docker-internal only, not reachable from host. Must use `ports: "9001:9001"`
- **redirect-to-https middleware**: Must use `@file` (not `@docker`) since defined in dynamic config files

## What NOT to Do

- Do not expose Prometheus (9090) or Grafana (3000) to the internet
- Do not commit `.env`, `rclone.conf`, `clients.json`, or SSH keys to git
- Do not run docker compose without `--env-file`
- Do not use PostgreSQL 16 — production backups require PG17
- Do not use Coolify — completely removed from architecture

## MCP Integration

Config at `/opt/odoo-mcp/odoo_config.json`. `create-odoo-instance.sh` auto-updates this file with new client instances.

## Network Architecture

```
Internet → Cloudflare Tunnel → Traefik (CommandCenter:80) → Dev Odoo containers
                                    ↓
                              Grafana (3000) — localhost only
                              GlitchTip (8001) — LAN only
                              Prometheus (9090) — localhost only

PROD Server (Hetzner) ← SSH/API ← CommandCenter
  Traefik (80/443) with Let's Encrypt auto-SSL
  Full KimKom-stack deployed via init-client.sh
  Prometheus exporters for monitoring
  Restic backups to KimKom S3
```
