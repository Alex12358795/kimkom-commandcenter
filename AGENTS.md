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
- `kimkom-modules` — shared and per-client Odoo modules (2-tier model)

## Directory Layout

```
/opt/kimkom-commandcenter/
  docker-compose.yml              # Traefik + PostgreSQL 17 + Portainer CE (shared)
  .env                             # POSTGRES_PASSWORD, GRAFANA_PASSWORD, etc. (not committed)
  instances/
    <client>/
      docker-compose.yml           # Odoo 18 container with Traefik labels
      Dockerfile                    # generator-defined dependencies (not a sentry-sdk guarantee)
      config/odoo.conf              # clean config; legacy instances may contain sentry_dsn (not committed)
      .env                          # DB_PASSWORD, ODOO_ADMIN_PASSWORD (not committed)
      addons/                       # legacy instance-local tree; unsupported for new clients
      addons-enterprise/            # Odoo Enterprise (not committed)
      addons-oca/                   # OCA community modules; legacy sentry content is not a clean-flow dependency
      data/                         # filestore volume — chown 100:101
  monitoring/
    docker-compose.yml              # Prometheus + Grafana + Alertmanager + Blackbox + exporters + Loki + Promtail
    prometheus.yml                  # scrape config + alertmanager linkage
    prometheus/rules/baseline.yml   # uptime, disk, backup, restore alert rules
    prometheus/targets/             # per-node exporter targets (nodes.yml, postgres.yml)
    blackbox/targets/               # HTTP (http.yml) and HTTPS (https.yml) probe targets
    alertmanager/alertmanager.yml   # generated runtime config (untracked, mode 0644)
    alertmanager/alertmanager.yml.template  # template with __TELEGRAM_BOT_TOKEN__ placeholder (committed)
    grafana/provisioning/
      dashboards/                   # 3 dashboards: node-exporter, postgresql, backup-v2
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
  update.sh                          # exact SHA/digest update with manual recovery
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
  .github/workflows/immutable-image.yml  # CI: build → push to GHCR

/opt/kimkom-modules/                 # Module repository (separate GitHub repo)
  shared/                            # modules shared across all KimKom clients
  <client-slug>/                     # client-specific modules (e.g., acme/)
  MODULES.md                         # module model documentation
```

## Phase 1 new-development module flow

This applies only to newly generated clients/modules. The generator creates and
configures a new development runtime; maintainers must initialize or update
the reviewed Git workspace separately through the module workflow under
`/opt/kimkom-modules/shared/` and `/opt/kimkom-modules/<client-slug>/` (or the
safe `KIMKOM_MODULES_ROOT` override). It never clones source. Containers mount
the client and shared paths separately, read-only; Odoo containers must never
write to source workspaces. Commit and push `kimkom-modules`, then release
only via CI-built images; there is no direct rsync-to-production workflow.

`scripts/deploy-module.sh` is unsupported for this flow. The existing
SuperTCG, Vranckeneers, and kimkom-dev instance-local trees are legacy and must
retain their current mounts; Phase 1 does not migrate them.

## Module Repository Model (2-Tier)

| Tier | Source | Per-instance? |
|---|---|---|
| Client | `/opt/kimkom-modules/<client-slug>/` | Only that client |
| Shared | `/opt/kimkom-modules/shared/` | Available to all clients |

Modules are developed directly in the workspace. Dev containers mount these
paths read-only. For production, modules are copied into the Docker build
context and baked into the image via CI.

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

# Fresh production provisioning (11 phases; do not add --resume)
cd /opt/KimKom-stack && ./init-client.sh --server <IP> --client <name> --domain <domain> \
  --odoo-image <digest> --backup-s3-key <key> --backup-s3-secret <secret> \
  --backup-escrow-reference <off-host-reference> --tailscale-token <tskey>
# Resume only after a failed run, and only with matching remote state/SHA.

# Deploy one exact immutable update to production
cd /opt/KimKom-stack && ./update.sh --server <IP> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2

# Run backup on production
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'
```

## Critical Rules

### Docker Compose — ALWAYS use --env-file

Legacy dev instances may have `.env` values for `DB_PASSWORD`,
`ODOO_ADMIN_PASSWORD`, and GlitchTip integration. Clean generated instances use
their generated DB/admin values; GlitchTip DSN is passed via `--glitchtip-dsn`
or left empty. Without `--env-file`, Odoo cannot connect to PostgreSQL.

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
- Projects created manually per customer; DSN stored in instance `.env`
- Legacy instance-specific sentry integration, where present, is not a clean
  generator guarantee and must not be copied from SuperTCG into a new client.

### Alertmanager + Telegram

- Config file is generated from template: `./scripts/generate-alertmanager-config.sh`
- Template: `monitoring/alertmanager/alertmanager.yml.template` (committed, has `__TELEGRAM_BOT_TOKEN__` placeholder)
- Generated: `monitoring/alertmanager/alertmanager.yml` (untracked, mode `0644`)
- Credentials are supplied from protected local secret storage; this guide does
  not reproduce any credential.
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
- Portainer CE 2.39.3 API may reject programmatic endpoint creation; enrollment is manual and remains pending until an observed endpoint ID is accepted
- UFW on PROD should allow port 9001 only from the CommandCenter Tailscale address

## Provisioning (init-client.sh)

11-phase resumable provisioning with state tracking via `.provision-state` on the target server. The deployment checkout is pinned and detached; updates do not use `git pull`. Monitoring onboarding appends targets directly to `nodes.yml`, `postgres.yml`, and `https.yml`, then restarts Prometheus.

**Phases:**
1. **server-bootstrap** — Docker, UFW, SSH hardening (via install.sh)
2. **git-clone** — Clone and check out the exact pinned SHA (preserves `.provision-state`)
3. **tailscale** — Enroll in Tailscale (if `--tailscale-token` provided)
4. **directories** — Create volume dirs, set filestore ownership
5. **env-setup** — Upload .env, dashboard auth, backup credentials (idempotent — reuses existing `.env`)
6. **dns-preflight** — Verify DNS resolves to target IP (no `curl -k`)
7. **odoo-init** — Start DB, pull/build Odoo, install modules, set admin password
8. **full-stack** — Start all Compose services
9. **health-check** — Verify HTTPS endpoint with valid TLS (no `-k`)
10. **backup-setup** — Install backup-v2 credentials, enable timers, first backup + verify
11. **monitoring-onboard** — Append Prometheus targets, restart Prometheus, print Portainer instructions

Flags: `--resume`, `--force-phase <name>`, `--reset-state`, `--tailscale-token <key>`, `--commandcenter-ip <ip>`, `--glitchtip-dsn <dsn>`

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
- Config: `/etc/kimkom-backup-v2.env` (root-only); application env is `$STACK_ROOT/.env`, not external `stack.env`
- Timers: backup (hourly), retention (daily), check (weekly), verify (monthly isolated restore)
- Verify script restores to isolated PostgreSQL and validates checksums and Odoo registry; this is not full Docker/PostgreSQL/Restic recovery evidence

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
- Do not use unsupported update flags such as `--ref`; use exact `--target-sha`, `--target-image`, and `--upgrade-modules`
- Do not treat a stopped Odoo service as a routed 503; no automatic rollback or traffic cutover is implemented

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
| Node Exporter – Server Resources | kimkom-node-exporter | CPU, memory, disk, network, load, uptime |
| PostgreSQL – CommandCenter Shared | kimkom-postgresql | Connections, transactions, tuples, DB size, cache hit ratio |
| Backup v2 – Status | kimkom-backup-v2 | Backup success/fail, last-backup age, restore verification, duration |

Grafana datasource UIDs: Prometheus=`PBFA97CFB590B2093`, Alertmanager=`alertmanager`, Loki=`loki`

## CI Pipeline (KimKom-stack)

Simple build-and-push to GHCR:
1. On push to `main`, build the Odoo image from `odoo/Dockerfile`.
2. Tag with the Git SHA.
3. Push to `ghcr.io/alex12358795/kimkom-odoo:<sha>`.
4. Use the resulting digest with `update.sh --target-image <image@sha256:digest>`.

No matrix, no schema-v3 manifests, no protected environments. Module source is
copied into the Docker build context at build time.

## Git History Sanitization

- CommandCenter repo was reinitialized with clean history (old commits contained SSH keys, Odoo passwords, Google service-account JSON)
- `.gitignore` prevents future credential leaks
- KimKom-stack history was already clean (placeholders only in all commits)
- All exposed credentials were rotated: SSH keys, DB passwords, admin passwords, GlitchTip token
