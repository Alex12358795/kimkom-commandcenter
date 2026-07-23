# KimKom-CommandCenter — Agent Guide

Central control plane for KimKom agency. Dev environments, monitoring, error tracking, and deployment tools for all clients.

## Infrastructure

| Node | Role | LAN IP | Tailscale IP |
|---|---|---|---|
| CommandCenter | Dev hosting, monitoring, GlitchTip, Portainer, backups | 192.168.178.19 | 100.67.52.95 |
| TEST | Production pilot (kimkom-prod) | 192.168.178.20 | 100.114.91.105 |

**Repos** (all private, on GitHub as Alex12358795):
- `kimkom-commandcenter` — this repo: dev instances, monitoring, GlitchTip, backup, dashboards
- `KimKom-stack` — production stack: init-client.sh, update.sh, backup-v2, Dockerfile, CI
- `kimkom-modules` — shared and per-client Odoo modules (4-tier model)

## Directory Layout

```
/opt/kimkom-commandcenter/
  docker-compose.yml              # Traefik + PostgreSQL 17 + Portainer CE (shared)
  .env                             # POSTGRES_PASSWORD, GRAFANA_PASSWORD, etc. (not committed)
  instances/
    <client>/
      docker-compose.yml           # Odoo 18 container with Traefik labels
      Dockerfile                    # pip installs including sentry-sdk>=2.0.0
      config/odoo.conf              # includes sentry_dsn (not committed)
      .env                          # DB_PASSWORD, ODOO_ADMIN_PASSWORD, GLITCHTIP_DSN (not committed)
      addons/                       # client-specific custom modules (tracked in kimkom-modules repo)
      addons-enterprise/            # Odoo Enterprise (not committed)
      addons-oca/                   # OCA community modules including sentry/ (not committed)
      data/                         # filestore volume — chown 100:101
  monitoring/
    docker-compose.yml              # Prometheus + Grafana + Alertmanager + Blackbox + exporters + Loki + Promtail
    prometheus.yml                  # scrape config + alertmanager linkage
    prometheus/rules/baseline.yml   # uptime, disk, backup, restore alert rules
    prometheus/targets/             # per-node exporter targets (nodes.yml, postgres.yml)
    blackbox/targets/               # HTTP (http.yml) and HTTPS (https.yml) probe targets
    alertmanager/alertmanager.yml   # Telegram receiver (not committed, generated from template)
    alertmanager/alertmanager.yml.template  # template with __TELEGRAM_BOT_TOKEN__ placeholder (committed)
    grafana/provisioning/
      dashboards/                   # 4 dashboards: customer-overview, node-exporter, postgresql, backup-v2
      datasources/                  # Prometheus (PBFA97CFB590B2093), Alertmanager, Loki
    grafana/data/                   # chown 472:472
    promtail/promtail.yml           # Docker container log scraping config
  glitchtip/
    docker-compose.yml              # GlitchTip error tracking (Tailscale-only :8001)
    .env                            # POSTGRES_PASSWORD, SECRET_KEY (not committed)
    dsns.json                       # project DSNs (not committed)
  scripts/
    create-odoo-instance.sh        # scaffold new dev client + DB role + MCP config
    backup-commandcenter.sh         # daily Restic backup (systemd timer)
    generate-alertmanager-config.sh # inject Telegram secrets into alertmanager.yml
    set-runtime-env.sh              # set management bind IPs
  systemd/
    kimkom-backup-cc.service        # daily backup systemd unit
    kimkom-backup-cc.timer           # daily at 00:01 UTC + randomised delay
  secrets/
    commandcenter/
      glitchtip-api-token           # GlitchTip API bearer token
      restic-password               # Restic repo encryption password
      alertmanager-secrets           # TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  ssh/
    deploy_key                      # SSH key for PROD servers (not committed)
    deploy_key.pub
  volumes/traefik/dynamic/
    login-rate-limit.yml             # rate-limit middleware (10 req/min avg, 20 burst)
  backup-repo/                       # local Restic repository (not committed)
  rclone/                            # Hetzner S3 remotes (not committed)

/opt/KimKom-stack/                   # PROD deployment repo (separate GitHub repo)
  init-client.sh                     # 11-phase resumable provisioning
  update.sh                          # exact-ref deployment + rollback
  docker-compose.yaml                # core + optional profiles
  docker-compose.local.yml           # HTTP-only override for LAN pilot
  odoo/Dockerfile                    # immutable image build (digest-pinned base)
  odoo/entrypoint.sh                 # sed-replaces placeholders in odoo.conf
  odoo/odoo.conf                     # template with __PLACEHOLDER__ values
  odoo/requirements.lock             # pinned Python deps
  clients/<slug>.yml                 # client manifest (modules, image, network)
  scripts/backup-v2/                 # backup, retention, check, verify-restore
  systemd/                           # backup timers (backup, retention, check, verify)
  lib/client-config.sh               # shared validation functions
  scripts/ci/                        # manifest validation, CI helpers
  .github/workflows/immutable-image.yml  # CI: validate → test-modules → build → scan → push

/opt/kimkom-modules/                 # Module repository (separate GitHub repo)
  shared/                            # modules shared across all KimKom clients
  <client-slug>/                     # client-specific modules (e.g., supertcg/, vranckeneers/)
  MODULES.md                         # module model documentation
```

## Module Repository Model (4-Tier)

| Tier | Source | Versioning | Per-instance? |
|---|---|---|---|
| Enterprise | Odoo's private GitHub repo | Tag-locked per Odoo 18 minor | All clients with Enterprise license |
| OCA | OCA GitHub repos | Pinned commit per repo | Selected per client manifest |
| Shared KimKom | `kimkom-modules/shared/` | Pinned commit | Selected per client manifest |
| Client-specific | `kimkom-modules/<client-slug>/` | Pinned commit | Only that client |

Client manifest (`clients/<slug>.yml`) specifies:
- `modules.kimkom_modules_repo` + `kimkom_modules_ref` — which commit to checkout
- `modules.shared` — list of shared module names to include
- `modules.client_dir` — which client directory to use
- `modules.enterprise.repo` + `tag` — Odoo Enterprise source
- `modules.oca[]` — OCA repos with ref + module list
- `modules.external[]` — third-party repos with ref + module list

CI builds one immutable Odoo image per customer by checking out all sources at pinned commits.

## Key Commands

```bash
# Start core services (Traefik + PostgreSQL 17 + Portainer CE)
cd /opt/kimkom-commandcenter && docker compose -p odoo-dev --env-file .env up -d

# Start monitoring (Prometheus + Grafana + Alertmanager + Loki + Promtail + exporters)
docker compose -f monitoring/docker-compose.yml --env-file .env up -d

# Start GlitchTip (error tracking, Tailscale-only)
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d

# Create new client dev instance (creates DB role, odoo.conf, compose, MCP config)
./scripts/create-odoo-instance.sh --client <name>

# Recreate a specific dev instance
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --force-recreate --wait --wait-timeout 300

# Restart all dev instances
for dir in /opt/kimkom-commandcenter/instances/*/; do
    docker compose -f "$dir/docker-compose.yml" --env-file "$dir/.env" restart
done

# Run CommandCenter backup manually
sudo ./scripts/backup-commandcenter.sh

# Generate alertmanager config from template + secrets
./scripts/generate-alertmanager-config.sh

# Provision a new production customer (resumable, 11 phases)
cd /opt/KimKom-stack && ./init-client.sh --server <IP> --client <name> --domain <domain> \
  --odoo-image <digest> --backup-s3-key <key> --backup-s3-secret <secret> \
  --tailscale-token <tskey> --resume

# Deploy an update to production
cd /opt/KimKom-stack && ./update.sh --server <IP> --client-slug <slug> --ref <git-ref>

# Run backup on production
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'cd /opt/kimkom-<slug> && sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env scripts/backup-v2/backup.sh'
```

## Critical Rules

### Docker Compose — ALWAYS use --env-file

Every dev instance has its own `.env` with `DB_PASSWORD`, `ODOO_ADMIN_PASSWORD`, and `GLITCHTIP_DSN`. Without `--env-file`, Odoo cannot connect to PostgreSQL.

```bash
# WRONG
docker compose -f instances/SuperTCG/docker-compose.yml up -d

# CORRECT
docker compose -f instances/SuperTCG/docker-compose.yml --env-file instances/SuperTCG/.env up -d
```

### Permissions

- Odoo data dirs: `sudo chown -R 100:101 instances/<client>/data` (Odoo runs as UID 100, GID 101)
- Odoo config files: owned by host user with group `101` and mode `0640` — mode `0600` causes `grep: /etc/odoo/odoo.conf: Permission denied` inside container
- Grafana data dir: `sudo chown -R 472:472 monitoring/grafana/data`
- Alertmanager config: mode `0644` (container runs as `nobody`, needs world-read)
- Secrets: mode `0600` under `0700` directories

### PostgreSQL 17

- Shared instance for all dev Odoo databases via `docker-compose.yml`
- Each client has a **dedicated non-superuser role** (e.g., `odoo_supertcg`, `odoo_vranckeneers`, `odoo_kimkom_dev`)
- Superuser `odoo` should NOT be used by individual instances
- Create a new role: `CREATE ROLE odoo_<slug> WITH LOGIN PASSWORD '<pw>';`
- Transfer DB ownership: `ALTER DATABASE "odoo<Name>" OWNER TO odoo_<slug>;`
- Grant schema privileges and default privileges for future tables/sequences
- Access: `docker exec -it odoo-postgres psql -U odoo -d odoomaster`
- **Production backups require PG17** (dump format v1.16). Do not use PG16.

### GlitchTip

- Internal only: `http://100.67.52.95:8001` (Tailscale, no external domain)
- API token stored at `secrets/commandcenter/glitchtip-api-token` (mode 0600)
- DSNs use Tailscale IP `100.67.52.95`, NOT LAN IP
- Odoo integration via OCA `sentry` module in `instances/<client>/addons-oca/sentry/`
- `sentry_dsn` is set directly in `odoo.conf` — NOT via entrypoint.sh on dev instances (entrypoint.sh is production-only)
- `sentry-sdk>=2.0.0` must be in the Dockerfile pip install line
- Module install (one-time): `docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env run --rm odoo -- -i sentry --stop-after-init --no-http`
- Sentry auto-initializes on subsequent Odoo starts via `post_load` hook
- Create a new project: `curl -X POST http://100.67.52.95:8001/api/0/teams/kimkom/kimkom/projects/ -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"name":"<slug>","slug":"<slug>"}'`
- Get DSN: `curl http://100.67.52.95:8001/api/0/projects/kimkom/<slug>/keys/ -H "Authorization: Bearer <token>"`

### Alertmanager + Telegram

- Config file is generated from template: `./scripts/generate-alertmanager-config.sh`
- Template: `monitoring/alertmanager/alertmanager.yml.template` (committed, has `__TELEGRAM_BOT_TOKEN__` placeholder)
- Generated: `monitoring/alertmanager/alertmanager.yml` (NOT committed, has real token)
- Secrets: `secrets/commandcenter/alertmanager-secrets` (contains `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`)
- Alertmanager does NOT support Docker-style `${VAR:default}` interpolation — use the generator script
- Config file must be mode `0644` (container runs as `nobody`)
- After changing config: `docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager`
- Validate: `docker exec odoo-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml`

### Loki + Promtail

- Loki runs at `127.0.0.1:3100` (localhost only)
- Promtail scrapes Docker container logs via `/var/run/docker.sock`
- Labels: `container_name`, `service`, `project`, `stream`
- Promtail filters by `project` label: `kimkom-commandcenter`, `odoo-dev`, `kimkom-prod`
- Grafana datasource UID: `loki`
- Old log entries (>1h) are rejected by Loki on first start — this is normal

### Traefik Login Rate Limiting

- Dynamic config at `volumes/traefik/dynamic/login-rate-limit.yml` (mounted via `--providers.file.directory`)
- Middleware: `login-rate-limit@file` (average 10/min, burst 20)
- Applied ONLY to login routers (`/web/login` and `/web/session/authenticate`), NOT to the main router
- Each instance has dedicated login routers with `priority=200`
- Main router has NO rate-limit middleware — normal browsing is unaffected

### Portainer

- **CE on CommandCenter**: `http://100.67.52.95:9000`, admin password in `.env`
- **Agent on PROD servers**: MUST use `ports: "9001:9001"` (NOT `expose: 9001`)
- Agent uses TLS by default (`use_tls=true`)
- Portainer CE 2.39.3 API may reject programmatic endpoint creation — add manually via UI
- UFW on PROD should allow port 9001 only from the CommandCenter Tailscale address

## Provisioning (init-client.sh)

11-phase resumable provisioning with state tracking via `.provision-state` on the target server:

1. **server-bootstrap** — Docker, UFW, SSH hardening (via install.sh)
2. **git-clone** — Clone or pull KimKom-stack repo
3. **tailscale** — Enroll in Tailscale (if `--tailscale-token` provided)
4. **directories** — Create volume dirs, set filestore ownership
5. **env-setup** — Upload .env, dashboard auth, backup credentials
6. **dns-preflight** — Verify DNS resolves to target IP (no `curl -k`)
7. **odoo-init** — Start DB, pull/build Odoo, install modules, set admin password
8. **full-stack** — Start all Compose services
9. **health-check** — Verify HTTPS endpoint with valid TLS (no `-k`)
10. **backup-setup** — Install backup-v2 credentials, enable timers, first backup + verify
11. **monitoring-onboard** — Add Prometheus/Blackbox targets on CommandCenter, create GlitchTip project

Flags: `--resume`, `--force-phase <name>`, `--reset-state`, `--tailscale-token <key>`, `--commandcenter-ip <ip>`

## Backup System

### CommandCenter Backup (`scripts/backup-commandcenter.sh`)
- Daily via systemd timer (`kimkom-backup-cc.timer`)
- Dumps: all PostgreSQL databases, GlitchTip database
- Copies: Odoo filestores, config/secrets, monitoring configs, GlitchTip config, Traefik dynamic config
- Restic repository: `local:/opt/kimkom-commandcenter/backup-repo`
- Password: `secrets/commandcenter/restic-password` (auto-generated if missing)
- Retention: 7 daily, 4 weekly, 6 monthly
- Runs as root (needs filestore access)

### Production Backup (`scripts/backup-v2/`)
- Online `pg_dump -Fc` (does NOT restart Odoo)
- Restic encrypted backup to Hetzner S3
- Config: `/etc/kimkom-backup-v2.env` (root-only)
- Timers: backup (hourly), retention (daily), check (weekly), verify (monthly isolated restore)
- Verify script restores to isolated PostgreSQL, validates checksums and Odoo registry

## DNS & SSL

**Local testing (CommandCenter dev behind Cloudflare Tunnel)**:
- Cloudflare Tunnel routes dev hostnames to `http://192.168.178.19:80`
- Traefik is HTTP-only (no Let's Encrypt on CommandCenter)
- Production hostname `kimkom-prod.kimkom.net` routes to `http://192.168.178.20:80`

**Production (Hetzner with public IP)**:
- Traefik auto-provisions Let's Encrypt SSL certs
- DNS must have A records for base domain AND all subdomains
- Port 80 must be free for Let's Encrypt HTTP-01 challenge

**Dynamic DNS (kimkom.be)**:
- OVH DynHost only updates existing A records — cannot create them
- Create A record first, then DynHost entry

## Common Mistakes

- **Port 80 conflict**: Check `docker ps | grep 80->80`
- **503 errors**: Check instance's `odoo-proxy` network attachment and Traefik labels
- **DB connection failure**: Ensure `.env` has correct `DB_PASSWORD` matching the PostgreSQL role password; ensure the role exists and has grants
- **Odoo config permission denied**: Config must be mode `0640` with group `101`, NOT `0600`
- **Alertmanager permission denied**: Config must be mode `0644` (container runs as `nobody`)
- **Promtail can't connect to Docker**: Mount `/var/run/docker.sock:/var/run/docker.sock:ro`
- **Login rate limit 404**: Traefik needs `--providers.file.directory=/etc/traefik/dynamic` and the dynamic volume mounted
- **sentry_dsn sed failure**: Use `|` delimiter in sed, not `/`
- **sentry-sdk version**: Manifest constrains `<=2.22.0` but pip installs 2.63.0. Relaxed to `>=2.0.0`
- **Portainer agent expose vs ports**: `expose: 9001` is Docker-internal only. Must use `ports: "9001:9001"`
- **Alertmanager `${VAR:default}`**: Alertmanager does NOT support Docker-style env interpolation. Use `generate-alertmanager-config.sh`
- **Git embedded repo warning**: Remove `.git` from nested module dirs before `git add`, or use `.gitignore` rule `instances/*/addons/*/.git/`

## What NOT to Do

- Do not expose Prometheus (9090), Grafana (3000), or Loki (3100) to the internet
- Do not commit `.env`, `odoo.conf`, `dsns.json`, SSH keys, API tokens, or `alertmanager.yml` to git
- Do not run docker compose without `--env-file`
- Do not use PostgreSQL 16 — production backups require PG17
- Do not use Coolify — completely removed from architecture
- Do not use the shared `odoo` superuser for individual dev instances — create dedicated roles
- Do not apply `login-rate-limit@file` to the main Odoo router — only to login-specific routers
- Do not store Restic passwords only on the target host — escrow off-site
- Do not claim image rollback alone is safe after an Odoo module upgrade — database changes are forward-only

## MCP Integration

- Odoo MCP config at `/opt/odoo-mcp/odoo_config.json`. `create-odoo-instance.sh` auto-updates.
- GlitchTip MCP at `/opt/glitchtip-mcp/server.py` registered in `/home/alex/.config/opencode/opencode.json`.
- GlitchTip API token loaded from `secrets/commandcenter/glitchtip-api-token` (not inline in config).

## Network Architecture

```
Internet → Cloudflare Tunnel → Traefik (CommandCenter:80) → Dev Odoo containers
                                    ↓
                              Grafana (3000) — Tailscale only
                              GlitchTip (8001) — Tailscale only
                              Portainer (9000) — Tailscale only
                              Prometheus (9090) — localhost only
                              Loki (3100) — localhost only
                              Alertmanager (9093) — localhost only

PROD Server (Hetzner/TEST) ← SSH ← CommandCenter (deploy_key)
  Traefik (80/443) with Let's Encrypt auto-SSL
  Full KimKom-stack deployed via init-client.sh (11-phase resumable)
  Prometheus exporters (Tailscale-only ports 9100, 9187)
  Portainer Agent (Tailscale-only port 9001)
  Restic backups to Hetzner S3 (hourly, daily retention)
  Backup verify (monthly isolated restore)
```

## Grafana Dashboards

| Dashboard | UID | Purpose |
|---|---|---|
| KimKom – Customer Overview | kimkom-customer-overview | Uptime, response time, DB connections, alerts, backup, disk, memory, SSL expiry, tool links |
| Node Exporter – Server Resources | kimkom-node-exporter | CPU, memory, disk, network, load, uptime |
| PostgreSQL – CommandCenter Shared | kimkom-postgresql | Connections, transactions, tuples, DB size, cache hit ratio |
| Backup v2 – Status | kimkom-backup-v2 | Backup success/fail, last-backup age, restore verification, duration |

Grafana datasource UIDs: Prometheus=`PBFA97CFB590B2093`, Alertmanager=`alertmanager`, Loki=`loki`

## CI Pipeline (KimKom-stack)

1. Developer pushes module branch to `kimkom-modules`
2. CI checks out `kimkom-modules` at pinned commit (from client manifest)
3. CI checks out OCA repos at pinned refs
4. CI runs Odoo lint (`-i base --stop-after-init`)
5. CI runs Odoo tests (`--test-enable --log-level=test`)
6. CI builds the immutable Odoo image
7. CI scans with Trivy (CRITICAL/HIGH severity)
8. CI pushes to GHCR with Git SHA tag
9. Deployment pulls image by digest via `update.sh`
10. Backup runs before upgrade

## Git History Sanitization

- CommandCenter repo was reinitialized with clean history (old commits contained SSH keys, Odoo passwords, Google service-account JSON)
- `.gitignore` prevents future credential leaks
- KimKom-stack history was already clean (placeholders only in all commits)
- All exposed credentials were rotated: SSH keys, DB passwords, admin passwords, GlitchTip token