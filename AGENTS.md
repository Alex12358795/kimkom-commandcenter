# KimKom CommandCenter — Agent Guide

Central control plane for the KimKom platform. Hosts dev Odoo instances, monitoring
(Prometheus/Grafana/Alertmanager/Loki), error tracking (GlitchTip), container management
(Portainer), and the backup/deployment tooling that drives production.

## Infrastructure

| Node | Role | LAN IP | Tailscale IP |
|---|---|---|---|
| CommandCenter | Dev hosting, monitoring, GlitchTip, Portainer, backups | 192.168.178.19 | 100.67.52.95 |
| PROD | Production — hosts the kimkom.be stack (`/opt/kimkom`) | 192.168.178.20 | 100.114.91.105 |

Both nodes are Proxmox VMs. SSH to both as `alex` using the deploy key at
`/opt/kimkom-commandcenter/ssh/deploy_key`.

### GitHub Repositories (all private, Alex12358795)

| Repo | Purpose |
|---|---|
| `kimkom-commandcenter` | This repo: dev instances, monitoring, GlitchTip, Portainer, backups, deployment scripts |
| `kimkom-deploy` | Production stack: `init-client.sh`, `update.sh`, `backup`, Dockerfile, CI, `docker-compose.yaml` |
| `kimkom-modules` | Shared and per-client Odoo module workspaces (checked out at `/opt/odoo-modules` on CommandCenter) |

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

## Component versions (2026-08-05)

| Component | Running | Latest | Action |
|---|---|---|---|
| Odoo 18 (dev) | 18.0-20260630 | 18.0.20260720 daily | none urgent |
| Traefik | 3.6.21 | 3.7.10 | minor |
| PostgreSQL 17 (dev) | 17.10 | 17.10 | patched ✓ |
| Grafana | 13.1.0 | 13.1.2 | **upgrade (CVE-2026-27876)** |
| Prometheus | 3.5.4 | 3.13.2 LTS | upgrade (3.5.x EOL 2026-07-31) |
| Loki | 3.5.5 | 3.7.5 | **upgrade (CVE-2026-21726/21729)** |
| Promtail | 3.5.5 | removed ≥3.7.3 | migrate to Alloy |
| Alertmanager | 0.33.1 | 0.33.1 | patched ✓ |
| node_exporter | 1.11.1 | 1.12.1 | minor |
| blackbox_exporter | 0.28.0 | 0.28.0 | patched ✓ |
| postgres_exporter | 0.20.0 | 0.20.1 | minor |
| cadvisor | 0.55.1 | 0.60.5 | minor |
| Portainer CE | :latest (digest) | 2.44.0 STS / 2.39.5 LTS | pin tag |
| GlitchTip | :latest (digest) | 6.2.x | pin ≥6.1.7 |
| Restic | system package | 0.19.1 | minor |
| Docker Engine | 29.6.0 | 29.7.0 | **upgrade (docker cp RCE)** |
| speaches | digest-pinned | — | OK |

## Undocumented-but-running services (as of 2026-08-05)

- **/opt/kimkom-sop** (compose project `kimkom-sop`): speech-to-text assistant
  stack. Services: `web` (Next.js, port 3000, Traefik route sop.kimkom.net),
  `api` (Python, port 8097, SQLite on ./data, mem_limit 4g),
  `speaches` (ghcr.io/speaches-ai/speaches, digest-pinned, internal).
  Hardened: cap_drop ALL, no-new-privileges, read_only, tmpfs, pids_limit,
  mem limits, healthchecks. Runs on the shared `odoo-proxy` Traefik network.
  NOT covered by backups. Started with
  `docker compose -f /opt/kimkom-sop/docker-compose.yml --env-file /opt/kimkom-sop/.env up -d`.
- **/opt/odoo-mcp** — MCP config for Odoo MCP server (`odoo_config.json`);
  referenced by `01-create-odoo-instance.sh` (registers new instances).
- **/opt/glitchtip-mcp** — MCP server (server.py) exposing GlitchTip API via MCP.
- **odoo-ci-db** — leftover `postgres:17` container in Created state (not running).

## Directory Layout

### CommandCenter (`/opt/kimkom-commandcenter/`)

```
docker-compose.yml              # Traefik + PostgreSQL 17 + Portainer CE
.env                             # POSTGRES_PASSWORD, GRAFANA_PASSWORD, etc (not committed)
.gitignore                       # secrets, .env, alertmanager.yml, backup-repo
odoo.conf.example                # tracked template with sentry placeholders (source for config/odoo.conf)
postgres/data/                   # PostgreSQL 17 volume data dir (generated, not committed)
portainer/data/                  # Portainer CE volume data dir (generated, not committed)
monitoring/
  docker-compose.yml              # Prometheus + Grafana + Alertmanager + Blackbox + exporters + Loki + Promtail + cadvisor
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
    dashboards/                    # 3 dashboards: node-exporter.json, postgresql.json, backup.json
    datasources/                   # Prometheus (PBFA97CFB590B2093), Alertmanager, Loki
  grafana/data/                    # chown 472:472
  promtail/promtail.yml            # Docker log scraping, filters by project label
  # cadvisor: odoo-cadvisor container (gcr.io/cadvisor/cadvisor:v0.55.1),
  # port 127.0.0.1:8080, scraped by Prometheus job "cadvisor"; feeds the
  # ManagedDevContainer* alert rules
glitchtip/
  docker-compose.yml              # GlitchTip web/worker/beat/Postgres/Redis (Tailscale-only)
  .env                            # POSTGRES_PASSWORD, SECRET_KEY (not committed)
  dsns.json                       # project DSNs (not committed)
scripts/
  01-create-odoo-instance.sh         # scaffold new dev client: DB role, odoo.conf, compose, resource limits
  02-update-modules.sh                # rsync Odoo modules over Tailscale, recovery point, odoo -u
  03-install-monitoring.sh            # idempotent: add Prometheus exporters + targets to a production VM
  04-generate-alertmanager-config.sh  # inject Telegram secrets into alertmanager.yml from secrets/
  05-backup-commandcenter.sh          # daily Restic backup of all DBs, filestores, configs
  adhoc-add-s3-remote.sh              # register a Hetzner S3 remote for rclone
  adhoc-set-runtime-env.sh            # set management bind IPs
  adhoc-test-generate-alertmanager-config.sh  # test harness for the Alertmanager config generator
systemd/
  kimkom-backup-cc.service         # daily backup unit
  kimkom-backup-cc.timer           # daily at 00:00 UTC + up to 30 min randomized delay
secrets/
  commandcenter/
    glitchtip-api-token            # GlitchTip API bearer token (mode 0600)
    glitchtip-admin-password       # GlitchTip admin password (mode 0600)
    restic-password                # CommandCenter Restic encryption password (mode 0600)
    alertmanager-secrets           # TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (mode 0600)
  kimkom/                          # production restic password (secrets/kimkom/restic-password)
  customer-ops/                    # leftover of the removed customer-ops feature (ignore)
ssh/
  deploy_key                       # SSH key for PROD servers (not committed, mode 0600)
  deploy_key.pub
tests/                             # stale __pycache__/test_customer_ops.cpython-314.pyc only (test source removed in 03332f3)
volumes/traefik/dynamic/
  login-rate-limit.yml             # rate-limit middleware: average 10/min, burst 20
backup-repo/                       # local Restic repository (not committed)
rclone/                            # Hetzner S3 remotes (not committed)
```

### Dev instances (`/opt/odoo-dev/<client>/`)

Legacy and generated dev instances live OUTSIDE the repo under
`/opt/odoo-dev/<client>/` (one directory per client, named after the client slug).
They are not tracked in git; only the generator script and this documentation
live in the repo. The backup script iterates `/opt/odoo-dev/*/`.

```
/opt/odoo-dev/supertcg/              # legacy dev instance (do NOT modify)
/opt/odoo-dev/vranckeneers/          # legacy dev instance (do NOT modify)
/opt/odoo-dev/kimkom/                # legacy test instance (do NOT modify)
/opt/odoo-dev/<new-client>/          # clean generated instance
  docker-compose.yml                 # Odoo 18 with Traefik labels, rate limiting, resource limits
  Dockerfile                         # generator-written dependencies
  config/odoo.conf                   # dedicated DB role, addons_path, no sentry-sdk guarantee
  .env                               # DB_PASSWORD, ODOO_ADMIN_PASSWORD (not committed, mode 0600)
  addons-enterprise/                 # per-instance enterprise addons (not committed)
  addons-oca/                        # per-instance OCA addons
  addons-external/                   # per-instance third-party addons (generator-only; legacy instances have none)
  data/                              # filestore — chown 100:101
```

Production stacks live at `/opt/<slug>/` on customer VMs (see kimkom-deploy).
kimkom.be production runs at `/opt/kimkom` on PROD (100.114.91.105), project
name `kimkom`, slug `kimkom`, tunnel-mode HTTP-only origin, local Restic repo.
Sentry/GlitchTip: the Odoo image bakes `odoo/.build-modules/source-addon-paths.json`
and phase 03 copies the vendored OCA tree (`odoo/.build-modules/oca/`) into
`addons-oca/` so `-i base,sentry` works at init; kimkom prod uses GlitchTip
project `kimkom` (id 4) on CommandCenter.

### kimkom-deploy (`/opt/kimkom-deploy/`)

```
init-client.sh                     # 11-phase resumable provisioning
01-join-tailscale.sh               # enroll a fresh server into the tailnet
02-install-stack.sh              # interactive wrapper: prompts for missing flags, --dry-run prints plan
update.sh                          # single-invocation update with recovery point
scripts/bootstrap-server.sh          # server prep: Docker, UFW, SSH hardening
remote-backup.sh                   # remote backup helper
docker-compose.yaml                # core: traefik, odoo-db, odoo, node-exporter, postgres-exporter, portainer-agent
docker-compose.local.yml           # HTTP-only override for local pilot
docker-compose.cloudflare.yml      # HTTP-only origin override for tunnel-mode production (behind Cloudflare tunnel)
odoo/
  Dockerfile                        # immutable image from digest-pinned base, pip requirements, custom modules
  entrypoint.sh                     # rewrites odoo.conf placeholders at startup
  odoo.conf                         # template with __PLACEHOLDER__ values
  requirements.lock                 # pinned Python deps
  modules/                          # scratch dir, empty in git (CI may push built artifacts here)
addons-oca/                         # runtime-mounted OCA addons incl. sentry
plausible/                          # clickhouse analytics, optional
scripts/
  backup/
    common.sh                       # shared config loading, Compose helpers, image/health/attachment checks
    backup.sh                       # online pg_dump + Restic filestore backup (hourly, non-atomic)
    recovery-point.sh               # quiesced paired DB+filestore recovery point (stop Odoo first)
    restore-recovery-point.sh       # prepare (isolated staging + neutralize) / apply (explicit destructive restore)
    retention.sh                    # daily Restic retention/prune
    check-repository.sh             # weekly Restic integrity check
    verify-restore.sh               # monthly isolated restore verification
    install.sh                      # install root-owned backup executables and systemd units
    config-verifier.sh              # validate root-owned backup config and credentials
    tests/
      phase2-fixtures.sh            # mocked control-flow fixture (not operational proof)
  set-stack-env.sh                  # set stack runtime env
  download-backup.sh                # download backup artifacts
clients/
  kimkom-prod.yml                   # client manifest: slug, display_name, domain
systemd/
  kimkom-backup.service          # hourly backup (ExecStart=/usr/local/libexec/kimkom-backup/backup.sh)
  kimkom-backup.timer
  kimkom-backup-retention.service
  kimkom-backup-retention.timer
  kimkom-backup-check.service
  kimkom-backup-check.timer
  kimkom-backup-verify.service
  kimkom-backup-verify.timer
  kimkom-backup.env.example      # template for /etc/kimkom-backup.env (root-only, mode 0600)
lib/
  client-config.sh                  # shared validation for slugs, paths, domains
volumes/                            # runtime volumes (generated)
.github/workflows/
  immutable-image.yml               # CI: workflow_dispatch manual trigger only (image rebuilds are rare)
.env.example                        # template for $STACK_ROOT/.env (mode 0600)
README.md
docs/
  BACKUP.md                        # backup design and operational contract
  RECOVERY.md                      # recovery prepare/apply contract and TEST-VM requirements
```

## Module Workflow

The platform uses a two-tier module model:

| Tier | Source | Scope |
|---|---|---|
| Client | `/opt/odoo-modules/<client-slug>/` | Only that client |
| Shared | `/opt/odoo-modules/shared/` | Available to all clients |

Modules are deployed via **rsync over Tailscale**, not baked into the Odoo image.
The image is rebuilt only for Odoo version bumps or Python dependency changes.

1. Develop modules in `/opt/odoo-modules/<client-slug>/` (dev containers mount read-only)
2. Commit and push to the `kimkom-modules` repo
3. Deploy with `scripts/02-update-modules.sh` on CommandCenter:
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
./scripts/01-create-odoo-instance.sh --client <name>

# Recreate a dev instance
docker compose -f /opt/odoo-dev/<client>/docker-compose.yml --env-file /opt/odoo-dev/<client>/.env up -d --force-recreate --wait
```

### Production — provisioning and updates

```bash
cd /opt/kimkom-deploy

# Interactive onboarding (guided; prompts for missing flags, --dry-run prints plan):
./02-install-stack.sh --dry-run

# Fresh production provisioning (11 phases, resumable).
# Full verified flag list + pre-flight checklist: SOP.md Section 4.
./init-client.sh --server <ts-ip> --client "<Name>" --client-slug <slug> \
  --domain <domain> --odoo-image "kimkom/odoo-local@sha256:<digest>" \
  --backup-s3-key <key> --backup-s3-secret <secret> \
  --backup-escrow-reference <ref> --restic-pass <password> \
  --github-deploy-key-file ~/.ssh/id_kimkom_github_<slug> \
  --tailscale-token <tskey> --commandcenter-ip 100.67.52.95 \
  --ssh-user alex --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key --non-interactive

# Cloudflare-tunnel production (HTTP-only origin, no public IP validation):
# e.g. kimkom.be — DNS proxied by Cloudflare, Traefik on 127.0.0.1:80 behind the
# tunnel, no Let's Encrypt, dns-preflight and public TLS check skipped.
./init-client.sh --server <ts-ip> --client "<Name>" --client-slug <slug> \
  --domain <domain> --odoo-image "kimkom/odoo-local@sha256:<digest>" \
  --cloudflare-tunnel --backup-target local \
  --backup-escrow-reference <ref> --restic-pass <password> \
  --github-deploy-key-file ~/.ssh/id_kimkom_github_<slug> \
  --ssh-user alex --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key --non-interactive

# Deploy an update (exact SHA/digest)
./update.sh --server <ip> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2
```

New init-client.sh flags: `--cloudflare-tunnel` (tunnel mode: skips
dns-preflight and public TLS check), `--backup-target s3|local` (default s3;
local uses a Restic repo on the VM itself — **not offsite**), `--restic-repository`
(override; default for local is `$STACK_DIR/backup-repo`), `--init-fresh-backup-repository`,
`--glitchtip-dsn` (enables `base,sentry` at init). Stack dir convention:
`/opt/<slug>` (legacy `/opt/kimkom-<slug>` still accepted). kimkom prod uses
`--cloudflare-tunnel --backup-target local` with repo `/opt/kimkom/backup-repo`.

### Production — backups and recovery

```bash
# Run backup on production
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<ts-ip> \
  'sudo /usr/local/libexec/kimkom-backup/backup.sh'

# Manual restore (quiesced recovery point)
sudo /usr/local/libexec/kimkom-backup/restore-recovery-point.sh prepare --id <ID>
sudo /usr/local/libexec/kimkom-backup/restore-recovery-point.sh apply --id <ID> --confirm-id <ID>
```

### CommandCenter — alerting and monitoring

```bash
# Generate Alertmanager config from template + secrets
./scripts/04-generate-alertmanager-config.sh

# Prometheus target health
curl -sS http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {labels: .labels, health}'

# Validate Prometheus config and rules
promtool check config monitoring/prometheus.yml
promtool check rules monitoring/prometheus/rules/baseline.yml
```

### Production — module updates

```bash
# Sync modules from CommandCenter to a customer VM, run odoo -u
/opt/kimkom-commandcenter/scripts/02-update-modules.sh \
    --slug supertcg --target-ts-ip <ts-ip> \
    --modules-source /opt/odoo-modules/supertcg \
    --upgrade-modules all
```

### Production — install monitoring on a new VM

```bash
# After init-client.sh finishes, connect the VM to Prometheus
/opt/kimkom-commandcenter/scripts/03-install-monitoring.sh \
    --client-slug supertcg --target-ts-ip <ts-ip>
```

## Critical Rules

### Docker Compose

**Always pass `--env-file`** when running `docker compose`. Without it, Odoo cannot
connect to PostgreSQL because the database password and admin password are missing.

```bash
# WRONG
docker compose -f /opt/odoo-dev/SuperTCG/docker-compose.yml up -d

# CORRECT
docker compose -f /opt/odoo-dev/supertcg/docker-compose.yml --env-file /opt/odoo-dev/supertcg/.env up -d
```

### Permissions

| Resource | Owner | Mode | Notes |
|---|---|---|---|
| Odoo data dirs | `100:101` | — | `chown -R 100:101 /opt/odoo-dev/<client>/data` |
| Instance `.env` | host user | `0600` | DB_PASSWORD, ODOO_ADMIN_PASSWORD |
| Grafana data dir | `472:472` | — | `chown -R 472:472 monitoring/grafana/data` |
| Alertmanager config | — | `0644` | Container runs as `nobody`; needs world-read |
| Secrets | — | `0600` | Under `0700` directories |

### PostgreSQL 17

- Shared PostgreSQL 17 instance for all dev Odoo databases
- Each client gets a **dedicated non-superuser role** (e.g., `odoo_<slug>`)
- Do NOT use the shared `odoo` superuser for individual dev instances
- Production backups require PG17 (dump format v1.16); do not use PG16

### Alertmanager + Telegram

- Config is generated from `alertmanager.yml.template` (with `__TELEGRAM_BOT_TOKEN__` and `__TELEGRAM_CHAT_ID__` placeholders) by running `./scripts/04-generate-alertmanager-config.sh`
- Generated runtime config: `alertmanager.yml` (untracked, mode `0644`)
- Credentials come from `secrets/commandcenter/alertmanager-secrets` (mode `0600`)
- Alertmanager does NOT support Docker-style `${VAR:default}` interpolation — use the generator script
- After changing config: `docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager`
- Validate: `docker exec odoo-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml`

## Backup & Recovery

### CommandCenter Backup

- Script: `scripts/05-backup-commandcenter.sh`
- Schedule: daily via systemd timer `kimkom-backup-cc.timer` (00:00 UTC + up to 30 min randomized delay (`OnCalendar=daily` + `RandomizedDelaySec=1800`))
- Scope: all PostgreSQL databases, GlitchTip database, Odoo filestores, config/secrets, monitoring configs, GlitchTip config, Traefik dynamic config
- Repository: local Restic at `/opt/kimkom-commandcenter/backup-repo`
- Encryption password: `secrets/commandcenter/restic-password` (mode `0600`)
- Retention: 7 daily, 4 weekly, 6 monthly
- Runs as root (needs filestore access)

### Production Backup (backup)

- Online `pg_dump -Fc` (does NOT restart Odoo)
- Restic encrypted backup to Hetzner S3 by default; `--backup-target local`
  uses a Restic repo on the VM itself (`$STACK_DIR/backup-repo`) — **not
  offsite**. kimkom prod deliberately uses the local target
  (`/opt/kimkom/backup-repo`, escrow reference `kimkom-prod-2026`).
- Config: `/etc/kimkom-backup.env` (root:root, mode `0600`); application env is `$STACK_ROOT/.env`
- Installed tools: `/usr/local/libexec/kimkom-backup/`
- Four systemd timers:
  - `kimkom-backup.timer` — hourly backup
  - `kimkom-backup-retention.timer` — daily retention/prune
  - `kimkom-backup-check.timer` — weekly integrity check
  - `kimkom-backup-verify.timer` — monthly isolated restore verification

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
- **Tunnel mode** (`--cloudflare-tunnel`): HTTP-only origin — Traefik binds
  `127.0.0.1:80` behind a token-mode Cloudflare tunnel, Cloudflare terminates
  TLS at the edge, no Let's Encrypt, DNS preflight skipped (kimkom.be is
  Cloudflare-proxied, dig returns edge IPs)

### Dynamic DNS (kimkom.be)

- OVH DynHost only updates existing A records — cannot create them
- Create the A record first, then the DynHost entry

## Limitations and Known Issues

- **Online backup is non-atomic**: the DB dump is consistent, but the filestore scan is not coordinated with it
- **Restore verification is structural only**: it does not prove real Docker/PostgreSQL/Restic recovery
- **No automatic rollback**: after a module upgrade failure, there is no automatic rollback or traffic cutover
- **Non-production alerts are muted**: Critical availability rules (`ManagedNodeUnavailable`, `ManagedPostgreSQLUnavailable`, `ManagedHTTPSUnavailable`) filter on `environment="production"`. Alertmanager has a `mute` route for `environment != "production"` that catches anything else — this remains the safety net for any future non-production targets; it does not affect kimkom.be (production, will page).
- **Transient alerts**: 2 alerts may fire after a container restart (auto-resolve)
- **Telegram bot token exposure**: the token was in git history — now untracked but not yet rotated (still unrotated as of 2026-08-05)
- **CI deploy key**: the `KIMKOM_MODULES_DEPLOY_KEY` secret must be configured in GitHub Actions
- **Module upgrade DB changes are forward-only**: image rollback alone is not safe after an Odoo module upgrade
- **Grafana upgraded to 13.1.2 on 2026-08-05** (fixes critical CVE-2026-27876 SQL-expressions RCE); mitigations remain: Tailscale-only bind, sqlExpressions toggle off.
- **Loki 3.5.5 affected by CVE-2026-21726 (path traversal) and CVE-2026-21729 (OOM)** — upgrade to ≥3.7.0 pending. Promtail is removed from Loki releases ≥3.7.3 (code merged into Grafana Alloy) — log pipeline must migrate to Alloy before the Loki upgrade.
- **Prometheus 3.5.x reached EOL 2026-07-31** — plan upgrade to 3.13.2 LTS.
- **Legacy Odoo instances run without resource limits** (generator-written instances get `cpus: 0.75` / `mem_limit: 1280m`; the 3 legacy ones run unlimited on a 9.2GiB host — swap at ~97%).
- **Production-side images must be ≥ postgres:17.10** (CVE-2026-6473/6637 authenticated RCE fixed in 17.10) — verify/upgrade on all customer VMs.
- **Phantom submodule**: the former gitlink `instances/SuperTCG/addons/kimkom_management_system` (mode 160000, NO .gitmodules entry) was removed from the index in the dev-instance relocation; the module lives on disk under `/opt/odoo-dev/supertcg/addons/kimkom_management_system` and is duplicated in /opt/odoo-modules/supertcg/.
- **/opt/kimkom-sop data is backed up** via `scripts/05-backup-commandcenter.sh` (section 6b, since 2026-08-05).
- **Pilot exporters removed** from Prometheus targets on 2026-08-05 (vranckeneers-prod on TEST VM 100.114.91.105 was dropped per CLIENT-REMOVAL.md); the VM now hosts the real kimkom.be production stack (monitoring targets re-added with `environment="production"` labels by installer phase 10).
- **promtool not installed on CommandCenter** — use `docker exec odoo-prometheus promtool` instead.

## What NOT to Do

- Do not commit `.env`, `odoo.conf`, `dsns.json`, SSH keys, API tokens, or `alertmanager.yml` to git
- Do not use PostgreSQL 16 — production backups require PG17
- Do not expose Prometheus (9090), Grafana (3000), or Loki (3100) to the internet — Tailscale or localhost only
- Do not use the shared `odoo` superuser for individual dev instances — create dedicated roles
- Do not modify legacy instances: SuperTCG, Vranckeneers, kimkom-dev
- Do not claim image rollback is safe after a module upgrade — database changes are forward-only
- Do not run `docker compose` without `--env-file`
