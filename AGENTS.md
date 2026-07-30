# KimKom CommandCenter — Agent Guide

Central control plane for the KimKom platform. Hosts dev Odoo instances, monitoring
(Prometheus/Grafana/Alertmanager/Loki), error tracking (GlitchTip), container management
(Portainer), and the backup/deployment tooling that drives production.

## Infrastructure

| Node | Role | LAN IP | Tailscale IP |
|---|---|---|---|
| CommandCenter | Dev hosting, monitoring, GlitchTip, Portainer, backups | 192.168.178.19 | 100.67.52.95 |
| TEST | Production pilot — KimKom-stack at `/opt/kimkom-kimkom-prod` | 192.168.178.20 | 100.114.91.105 |

Both nodes are Proxmox VMs. SSH to both as `alex` using the deploy key at
`/opt/kimkom-commandcenter/ssh/deploy_key`.

### GitHub Repositories (all private, Alex12358795)

| Repo | Purpose |
|---|---|
| `kimkom-commandcenter` | This repo: dev instances, monitoring, GlitchTip, Portainer, backups, deployment scripts |
| `KimKom-stack` | Production stack: `init-client.sh`, `update.sh`, `backup-v2`, Dockerfile, CI, `docker-compose.yaml` |
| `kimkom-modules` | Shared and per-client Odoo module workspaces |

## Service Endpoints

| Service | URL | Access |
|---|---|---|
| Grafana | http://100.67.52.95:3000 | Tailscale only |
| GlitchTip | http://100.67.52.95:8001 | Tailscale only |
| Portainer | http://100.67.52.95:9000 | Tailscale only |
| Prometheus | http://localhost:9090 | Localhost only |
| Loki | http://localhost:3100 | Localhost only |
| Alertmanager | http://localhost:9093 | Localhost only |

Grafana datasources: Prometheus (`PBFA97CFB590B2093`), Alertmanager, Loki.

## Directory Layout

### CommandCenter (`/opt/kimkom-commandcenter/`)

```
docker-compose.yml              # Traefik + PostgreSQL 17 + Portainer CE
.env                             # POSTGRES_PASSWORD, GRAFANA_PASSWORD, etc (not committed)
.gitignore                       # secrets, .env, alertmanager.yml, backup-repo
instances/
  SuperTCG/                      # legacy dev instance (do NOT modify)
  vranckeneers/                  # legacy dev instance (do NOT modify)
  kimkom-dev/                    # legacy test instance (do NOT modify)
  <new-client>/                  # clean generated instance
    docker-compose.yml           # Odoo 18 with Traefik labels, rate limiting, resource limits
    Dockerfile                   # generator-written dependencies
    config/odoo.conf             # dedicated DB role, addons_path, no sentry-sdk guarantee
    .env                         # DB_PASSWORD, ODOO_ADMIN_PASSWORD (not committed, mode 0640)
    addons-enterprise/           # per-instance enterprise addons (not committed)
    addons-oca/                  # per-instance OCA addons
    addons-external/             # per-instance third-party addons
    data/                        # filestore — chown 100:101
monitoring/
  docker-compose.yml              # Prometheus + Grafana + Alertmanager + Blackbox + exporters + Loki + Promtail
  prometheus.yml                  # scrape config, file-SD targets, alertmanager linkage
  prometheus/rules/baseline.yml   # 17 alert rules: node, PostgreSQL, HTTPS, disk, memory, swap, backup, containers
  prometheus/targets/
    nodes.yml                     # node exporter targets with client labels
    postgres.yml                  # PostgreSQL exporter targets
  blackbox/targets/
    http.yml                      # HTTP probe targets
    https.yml                     # HTTPS probe targets
  alertmanager/
    alertmanager.yml              # generated runtime config (untracked, mode 0644)
    alertmanager.yml.template      # template with __TELEGRAM_BOT_TOKEN__ and __TELEGRAM_CHAT_ID__ placeholders
  grafana/provisioning/
    dashboards/                    # 3 dashboards: node-exporter.json, postgresql.json, backup-v2.json
    datasources/                   # Prometheus (PBFA97CFB590B2093), Alertmanager, Loki
  grafana/data/                    # chown 472:472
  promtail/promtail.yml            # Docker log scraping, filters by project label
glitchtip/
  docker-compose.yml              # GlitchTip web/worker/beat/Postgres/Redis (Tailscale-only)
  .env                            # POSTGRES_PASSWORD, SECRET_KEY (not committed)
  dsns.json                       # project DSNs (not committed)
scripts/
  create-odoo-instance.sh         # scaffold new dev client: DB role, odoo.conf, compose, resource limits
  backup-commandcenter.sh          # daily Restic backup of all DBs, filestores, configs
  generate-alertmanager-config.sh  # inject Telegram secrets into alertmanager.yml from secrets/
  set-runtime-env.sh              # set management bind IPs
systemd/
  kimkom-backup-cc.service         # daily backup unit
  kimkom-backup-cc.timer           # daily at 00:01 UTC + randomized delay
secrets/
  commandcenter/
    glitchtip-api-token            # GlitchTip API bearer token (mode 0600)
    restic-password                # CommandCenter Restic encryption password (mode 0600)
    alertmanager-secrets           # TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (mode 0600)
ssh/
  deploy_key                       # SSH key for PROD servers (not committed, mode 0600)
  deploy_key.pub
volumes/traefik/dynamic/
  login-rate-limit.yml             # rate-limit middleware: average 10/min, burst 20
backup-repo/                       # local Restic repository (not committed)
rclone/                            # Hetzner S3 remotes (not committed)
```

### KimKom-stack (`/opt/KimKom-stack/`)

```
init-client.sh                     # 11-phase resumable provisioning
update.sh                          # single-invocation update with recovery point
docker-compose.yaml                # core: traefik, odoo-db, odoo, node-exporter, postgres-exporter, portainer-agent
docker-compose.local.yml           # HTTP-only override for local pilot
odoo/
  Dockerfile                        # immutable image from digest-pinned base, pip requirements, custom modules
  entrypoint.sh                     # rewrites odoo.conf placeholders at startup
  odoo.conf                         # template with __PLACEHOLDER__ values
  requirements.lock                 # pinned Python deps
  modules/                          # scratch: CI may push built artifacts here (ignored by git)
    kimkom-prod/README.md           # placeholder
    enterprise/README.md            # placeholder (supplied by private build)
    oca/sentry/                     # OCA sentry module for GlitchTip integration
clients/
  kimkom-prod.yml                   # client manifest: slug, display_name, domain
scripts/backup-v2/
  common.sh                         # shared config loading, Compose helpers, image/health/attachment checks
  backup.sh                         # online pg_dump + Restic filestore backup (hourly, non-atomic)
  recovery-point.sh                 # quiesced paired DB+filestore recovery point (stop Odoo first)
  restore-recovery-point.sh         # prepare (isolated staging + neutralize) / apply (explicit destructive restore)
  retention.sh                      # daily Restic retention/prune
  check-repository.sh               # weekly Restic integrity check
  verify-restore.sh                 # monthly isolated restore verification
  install.sh                        # install root-owned backup executables and systemd units
  config-verifier.sh               # validate root-owned backup config and credentials
  tests/
    phase2-fixtures.sh              # mocked control-flow fixture (not operational proof)
systemd/
  kimkom-backup-v2.service          # hourly backup (ExecStart=/usr/local/libexec/kimkom-backup-v2/backup.sh)
  kimkom-backup-v2.timer
  kimkom-backup-v2-retention.service
  kimkom-backup-v2-retention.timer
  kimkom-backup-v2-check.service
  kimkom-backup-v2-check.timer
  kimkom-backup-v2-verify.service
  kimkom-backup-v2-verify.timer
  kimkom-backup-v2.env.example      # template for /etc/kimkom-backup-v2.env (root-only, mode 0600)
lib/
  client-config.sh                  # shared validation for slugs, paths, domains
.github/workflows/
  immutable-image.yml               # CI: workflow_dispatch manual trigger only (image rebuilds are rare)
.env.example                        # template for $STACK_ROOT/.env (mode 0600)
README.md
BACKUP-V2.md                        # backup design and operational contract
RECOVERY-V2.md                      # recovery prepare/apply contract and TEST-VM requirements
```

## Module Workflow

The platform uses a two-tier module model:

| Tier | Source | Scope |
|---|---|---|
| Client | `/opt/kimkom-modules/<client-slug>/` | Only that client |
| Shared | `/opt/kimkom-modules/shared/` | Available to all clients |

Modules are deployed via **rsync over Tailscale**, not baked into the Odoo image.
The image is rebuilt only for Odoo version bumps or Python dependency changes.

1. Develop modules in `/opt/kimkom-modules/<client-slug>/` (dev containers mount read-only)
2. Commit and push to the `kimkom-modules` repo
3. Deploy with `scripts/update-modules.sh` on CommandCenter:
   - rsyncs modules to the customer VM over Tailscale
   - Creates a quiesced recovery point before swapping
   - Atomically swaps modules, runs `odoo -u`, health check
4. CI image builds are **manual only** (`workflow_dispatch`) — no trigger on push
5. Enterprise, OCA, and shared modules are runtime mounts on the production server, not rsynced each update

## Key Commands

### CommandCenter — start services

```bash
# Core services (Traefik + PostgreSQL 17 + Portainer CE)
cd /opt/kimkom-commandcenter && docker compose -p odoo-dev --env-file .env up -d

# Monitoring (Prometheus + Grafana + Alertmanager + Loki + Promtail + exporters)
docker compose -f monitoring/docker-compose.yml --env-file .env up -d

# GlitchTip (error tracking, Tailscale-only)
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d
```

### CommandCenter — dev instances

```bash
# Create a new dev instance
./scripts/create-odoo-instance.sh --client <name>

# Recreate a dev instance
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --force-recreate --wait
```

### Production — provisioning and updates

```bash
cd /opt/KimKom-stack

# Fresh production provisioning (11 phases)
./init-client.sh --server <ip> --client <name> --client-slug <slug> --domain <domain> \
  --odoo-image <image@sha256:digest> --backup-s3-key <key> --backup-s3-secret <secret> \
  --backup-escrow-reference <ref> --tailscale-token <tskey>

# Deploy an update (exact SHA/digest)
./update.sh --server <ip> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2
```

### Production — backups and recovery

```bash
# Run backup on production
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<ts-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'

# Manual restore (quiesced recovery point)
sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh prepare --id <ID>
sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh apply --id <ID> --confirm-id <ID>
```

### CommandCenter — alerting and monitoring

```bash
# Generate Alertmanager config from template + secrets
./scripts/generate-alertmanager-config.sh

# Prometheus target health
curl -sS http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {labels: .labels, health}'

# Validate Prometheus config and rules
promtool check config monitoring/prometheus.yml
promtool check rules monitoring/prometheus/rules/baseline.yml
```

## Critical Rules

### Docker Compose

**Always pass `--env-file`** when running `docker compose`. Without it, Odoo cannot
connect to PostgreSQL because the database password and admin password are missing.

```bash
# WRONG
docker compose -f instances/SuperTCG/docker-compose.yml up -d

# CORRECT
docker compose -f instances/SuperTCG/docker-compose.yml --env-file instances/SuperTCG/.env up -d
```

### Permissions

| Resource | Owner | Mode | Notes |
|---|---|---|---|
| Odoo data dirs | `100:101` | — | `chown -R 100:101 instances/<client>/data` |
| Instance `.env` | host user | `0640` | DB_PASSWORD, ODOO_ADMIN_PASSWORD |
| Grafana data dir | `472:472` | — | `chown -R 472:472 monitoring/grafana/data` |
| Alertmanager config | — | `0644` | Container runs as `nobody`; needs world-read |
| Secrets | — | `0600` | Under `0700` directories |

### PostgreSQL 17

- Shared PostgreSQL 17 instance for all dev Odoo databases
- Each client gets a **dedicated non-superuser role** (e.g., `odoo_<slug>`)
- Do NOT use the shared `odoo` superuser for individual dev instances
- Production backups require PG17 (dump format v1.16); do not use PG16

### Alertmanager + Telegram

- Config is generated from `alertmanager.yml.template` (with `__TELEGRAM_BOT_TOKEN__` and `__TELEGRAM_CHAT_ID__` placeholders) by running `./scripts/generate-alertmanager-config.sh`
- Generated runtime config: `alertmanager.yml` (untracked, mode `0644`)
- Credentials come from `secrets/commandcenter/alertmanager-secrets` (mode `0600`)
- Alertmanager does NOT support Docker-style `${VAR:default}` interpolation — use the generator script
- After changing config: `docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager`
- Validate: `docker exec odoo-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml`

## Backup & Recovery

### CommandCenter Backup

- Script: `scripts/backup-commandcenter.sh`
- Schedule: daily via systemd timer `kimkom-backup-cc.timer` (00:01 UTC + randomized delay)
- Scope: all PostgreSQL databases, GlitchTip database, Odoo filestores, config/secrets, monitoring configs, GlitchTip config, Traefik dynamic config
- Repository: local Restic at `/opt/kimkom-commandcenter/backup-repo`
- Encryption password: `secrets/commandcenter/restic-password` (mode `0600`)
- Retention: 7 daily, 4 weekly, 6 monthly
- Runs as root (needs filestore access)

### Production Backup (backup-v2)

- Online `pg_dump -Fc` (does NOT restart Odoo)
- Restic encrypted backup to Hetzner S3
- Config: `/etc/kimkom-backup-v2.env` (root:root, mode `0600`); application env is `$STACK_ROOT/.env`
- Installed tools: `/usr/local/libexec/kimkom-backup-v2/`
- Four systemd timers:
  - `kimkom-backup-v2.timer` — hourly backup
  - `kimkom-backup-v2-retention.timer` — daily retention/prune
  - `kimkom-backup-v2-check.timer` — weekly integrity check
  - `kimkom-backup-v2-verify.timer` — monthly isolated restore verification

### Recovery Points

- Quiesced paired DB+filestore recovery point created **before module upgrades** (stops Odoo first)
- Manual two-step restore:
  1. `prepare --id <ID>` — isolated staging + neutralize
  2. `apply --id <ID> --confirm-id <ID>` — explicit destructive restore

### Verification

- Monthly isolated restore to a separate PostgreSQL instance
- Validates checksums and runs `pg_restore`
- Runs Odoo registry check
- Checks structure only — not full Docker/PostgreSQL/Restic recovery evidence

## DNS & SSL

### CommandCenter (dev)

- Cloudflare Tunnel routes dev hostnames to `http://192.168.178.19:80`
- Traefik is HTTP-only — no Let's Encrypt on CommandCenter

### Production

- Traefik auto-provisions Let's Encrypt SSL certificates
- Requires ports 80/443 to be free on the target server
- DNS must have A records for the base domain and all subdomains

### Dynamic DNS (kimkom.be)

- OVH DynHost only updates existing A records — cannot create them
- Create the A record first, then the DynHost entry

## Limitations and Known Issues

- **Online backup is non-atomic**: the DB dump is consistent, but the filestore scan is not coordinated with it
- **Restore verification is structural only**: it does not prove real Docker/PostgreSQL/Restic recovery
- **No automatic rollback**: after a module upgrade failure, there is no automatic rollback or traffic cutover
- **Transient alerts**: 2 alerts may fire after a container restart (auto-resolve)
- **Telegram bot token exposure**: the token was in git history — now untracked but not yet rotated
- **CI deploy key**: the `KIMKOM_MODULES_DEPLOY_KEY` secret must be configured in GitHub Actions
- **Module upgrade DB changes are forward-only**: image rollback alone is not safe after an Odoo module upgrade

## What NOT to Do

- Do not commit `.env`, `odoo.conf`, `dsns.json`, SSH keys, API tokens, or `alertmanager.yml` to git
- Do not use PostgreSQL 16 — production backups require PG17
- Do not expose Prometheus (9090), Grafana (3000), or Loki (3100) to the internet — Tailscale or localhost only
- Do not use the shared `odoo` superuser for individual dev instances — create dedicated roles
- Do not modify legacy instances: SuperTCG, Vranckeneers, kimkom-dev
- Do not claim image rollback is safe after a module upgrade — database changes are forward-only
- Do not run `docker compose` without `--env-file`
