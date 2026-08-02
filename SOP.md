# KimKom — Standard Operating Procedures

Operator runbook for the KimKom platform. Day-to-day operations: adding clients, developing modules, deploying to production, upgrades, rollbacks, and disaster recovery.

---

## Table of Contents

1. [Infrastructure Overview](#1-infrastructure-overview)
2. [Starting and Stopping Services](#2-starting-and-stopping-services)
3. [Adding a New Dev Client](#3-adding-a-new-dev-client)
4. [Adding a New Production Customer](#4-adding-a-new-production-customer)
5. [Deploying Updates to Production](#5-deploying-updates-to-production)
6. [Backups and Restore](#6-backups-and-restore)
7. [Monitoring and Alerts](#7-monitoring-and-alerts)
8. [Module Development Workflow](#8-module-development-workflow)
9. [DNS and SSL](#9-dns-and-ssl)
10. [Troubleshooting](#10-troubleshooting)
11. [Credentials Reference](#11-credentials-reference)
12. [Quick Reference](#12-quick-reference)

---

## 1. Infrastructure Overview

| Node | Role | LAN IP | Tailscale IP |
|---|---|---|---|
| CommandCenter | Dev hosting, monitoring, GlitchTip, Portainer, backups | 192.168.178.19 | 100.67.52.95 |
| TEST VM | Production pilot (kimkom-prod) | 192.168.178.20 | 100.114.91.105 |

- **CommandCenter** is a Proxmox VM at home. Runs Traefik, shared PostgreSQL, Portainer, Prometheus, Grafana, Alertmanager, Loki, Promtail, and GlitchTip.
- **TEST VM** (100.114.91.105) hosts KimKom-stack pilots. As of 2026-08-02 it runs the `vranckeneers-prod` fake client, which was used to prove the fresh-client onboarding flow end-to-end (Section 4); it previously hosted `kimkom-prod`.
- **Clients:**
  - SuperTCG (legacy)
  - Vranckeneers (legacy)
  - kimkom-dev (legacy)
  - kimkom-prod (superseded TEST pilot)
  - vranckeneers-prod (TEST pilot — E2E drill client as of 2026-08-02)
- **Legacy instances MUST NOT be modified.** They retain their instance-local mounts.
- **New dev instances** are created with `create-odoo-instance.sh` and mount modules from `/opt/kimkom-modules`.

**Repositories** (all private, on GitHub as Alex12358795):
- `kimkom-commandcenter` — this machine: dev instances, monitoring, GlitchTip, backup, dashboards
- `KimKom-stack` — production deployment scripts
- `kimkom-modules` — shared and per-client Odoo modules

---

## 2. Starting and Stopping Services

### CommandCenter

```bash
# Core (Traefik + PostgreSQL + Portainer)
cd /opt/kimkom-commandcenter && docker compose -p odoo-dev --env-file .env up -d

# Monitoring (Prometheus + Grafana + Alertmanager + exporters + Loki + Promtail)
docker compose -f monitoring/docker-compose.yml --env-file .env up -d

# GlitchTip
docker compose -f glitchtip/docker-compose.yml --env-file glitchtip/.env up -d
```

### Dev instances

```bash
# Recreate a specific instance
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --force-recreate --wait --wait-timeout 300

# Restart all dev instances
for d in instances/*/; do docker compose -f "$d/docker-compose.yml" --env-file "$d/.env" restart; done
```

### Grafana, GlitchTip, Portainer

These services are Tailscale-only, accessible on `100.67.52.95`:

| Service | Port | Access |
|---|---|---|
| Grafana | 3000 | http://100.67.52.95:3000 |
| GlitchTip | 8001 | http://100.67.52.95:8001 |
| Portainer | 9000 | http://100.67.52.95:9000 |

- Grafana admin password is in `.env` (`GRAFANA_PASSWORD`).
- GlitchTip admin is at http://100.67.52.95:8001.
- Portainer admin password is in `.env` (`PORTAINER_ADMIN_PASSWORD`).

---

## 3. Adding a New Dev Client

```bash
cd /opt/kimkom-commandcenter
./scripts/create-odoo-instance.sh --client <name>
```

This creates:
- `instances/<name>/` directory
- PostgreSQL role `odoo_<name>` and database `odoo_<name>`
- Compose file with resource limits: `cpus 0.75`, `mem_limit 1280m`, `pids_limit 256`, `workers=0`, `max_cron_threads=1`, PostgreSQL `CONNECTION LIMIT 10`
- Read-only module mounts from `/opt/kimkom-modules/<name>/`
- Starts the instance

The instance will be available at `https://<name>.kimkom.net`.

---

## 4. Adding a New Production Customer

> **Status: verified end-to-end** in the 2026-08-02 drills on the TEST VM
> (100.114.91.105, fake client `vranckeneers-prod`). The flow below matches the
> tooling exactly — flags, phases, and validation order come from
> `KimKom-stack/init-client.sh` and `scripts/phases/phase-lib.sh`.

### Pre-flight checklist (operator prerequisites)

Gather everything below **before** running `init-client.sh`:

| # | Item | How to obtain / verify |
|---|---|---|
| 1 | Dedicated server (Ubuntu + Docker) | Reachable over SSH; ports 80/443 free for TLS production |
| 2 | Tailscale authkey | `https://login.tailscale.com/admin/settings/keys` → generate; pre-auth the node |
| 3 | Per-customer GitHub deploy key for KimKom-stack | See **Step 2** below |
| 4 | S3 bucket + credentials | Hetzner Object Storage: bucket `<slug>-prod`, dedicated backup access key/secret; credentials file will be installed to `/etc/kimkom-backup/aws-credentials` |
| 5 | Restic repository | `RESTIC_REPOSITORY` env override, or the default `s3:https://fsn1.your-objectstorage.com/<namespace>-prod` (verify the current Hetzner endpoint — `.de` vs `.com` — against today's Hetzner docs) |
| 6 | Restic password | `--restic-pass` (installed to `/etc/kimkom-backup/restic-password`) |
| 7 | Domain DNS | A record for `<domain>` and `*.domain` → public IP; `dns-preflight` phase verifies this |
| 8 | Escrow reference | Non-secret off-host record of the S3 repo + Restic password location (`--backup-escrow-reference`) |
| 9 | Odoo image | Immutable digest `kimkom/odoo-local@sha256:<digest>` — built locally (Step 3) or pulled from GHCR |
| 10 | GlitchTip DSN (optional) | Existing project DSN via `--glitchtip-dsn` to enable the Odoo Sentry module |

### Step 1 — Tailscale bootstrap (operator-side, from CommandCenter)

Run the dedicated bootstrap script — it installs Tailscale, enrolls the node,
verifies the join (default route + DNS unchanged, node pingable over the mesh),
and prints the Tailscale IP for `init-client.sh --server`:

```bash
cd /opt/KimKom-stack
./scripts/bootstrap-tailscale.sh \
  --server <public-ip> \          # bootstrap ONLY — all later access is over Tailscale
  --hostname <client-slug> \
  --auth-key tskey-auth-... \     # operator-generated; or file:<path>
  --ssh-user root \
  --ssh-key <bootstrap-key>
```

The script is idempotent (an already-enrolled node is detected and kept) and
safely refuses to enroll if Tailscale would hijack the server's default route
or DNS. Verify manually if you prefer: `tailscale ping <ts-ip>` from the
CommandCenter.

### Step 2 — GitHub deploy key for the private clone

Phase `01-git-clone` needs a **distinct per-customer GitHub deploy key** to clone
the private `KimKom-stack` repo. The CommandCenter's own deploy key
(`/opt/kimkom-commandcenter/ssh/deploy_key`) is intentionally NOT usable for this
and `install.sh` refuses to copy it — the drill workaround (git bundle + local
bare repo) is for drills only, never production.

Production procedure:

```bash
# On CommandCenter, generate a per-customer keypair (no passphrase)
ssh-keygen -t ed25519 -f ~/.ssh/id_kimkom_github_<slug> -N ""
```

1. Add `~/.ssh/id_kimkom_github_<slug>.pub` to the KimKom-stack GitHub repo:
   Settings → Deploy keys → Add deploy key (read-only).
2. Pass the **private key path** to `init-client.sh` via `--github-deploy-key-file <path>`.

### Step 3 — Build and deliver the Odoo image

The image is built on the CommandCenter and shipped to the target over SSH
(docker save/load — no registry needed):

```bash
cd /opt/KimKom-stack
docker build --tag kimkom/odoo-local:latest \
    --build-arg CLIENT_SLUG=<slug> \
    -f odoo/Dockerfile odoo/

# Deliver the image to the target VM
docker save kimkom/odoo-local:latest | ssh -C <user>@<ts-ip> docker load

# Record the digest for --odoo-image
ssh <user>@<ts-ip> 'docker images kimkom/odoo-local --digests'
```

> Production note: GHCR-hosted immutable images (`ghcr.io/alex12358795/...`)
> are the long-term path; the local build + `docker save | ssh docker load`
> flow is what the drills proved. For `--allow-local-build` runs the digest is
> resolved from the locally built image.

### Step 4 — Provision (init-client.sh, 11 phases, resumable)

Run from a clean checkout of `KimKom-stack`:

```bash
cd /opt/KimKom-stack
./init-client.sh --server <ts-ip> \
  --client "<Name>" \
  --client-slug <slug> \
  --domain <domain> \
  --odoo-image "kimkom/odoo-local@sha256:<digest>" \
  --backup-s3-key <key> --backup-s3-secret <secret> \
  --backup-escrow-reference <off-host-ref> \
  --restic-pass <password> \
  --github-deploy-key-file ~/.ssh/id_kimkom_github_<slug> \
  --tailscale-token <tskey> \
  --commandcenter-ip 100.67.52.95 \
  --ssh-user alex \
  --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key \
  --non-interactive
```

The 11 phases run in order (each is a phase script in `scripts/phases/`):

`00-server-bootstrap`, `01-git-clone`, `02-tailscale`, `03-directories`,
`04-env-setup`, `05-dns-preflight`, `06-odoo-init`, `07-full-stack`,
`08-health-check`, `09-backup-setup`, `10-monitoring-onboard`

**Resumability / state flags** (verified in the drills):

- `--resume` — continue a failed run from the last completed phase (required
  when remote provisioning state already exists)
- `--force-phase <name>` — re-run a phase **and everything downstream**
  (e.g. `--force-phase full-stack` re-runs full-stack + health-check +
  backup-setup + monitoring-onboard); re-run the full command with the flag
- `--reset-state` — clear provisioning state only (never combine with
  `--resume` or `--force-phase`)

**Restic repository override** — `RESTIC_REPOSITORY` is an env override,
default-only since `73aebd3`:

```bash
RESTIC_REPOSITORY=/var/lib/kimkom-test-repo ./init-client.sh ...
```

For production, leave it unset (defaults to
`s3:https://fsn1.your-objectstorage.com/<namespace>-prod`) or set it explicitly
to the customer bucket.

**Pilot-only flags — NEVER for production:**

- `--local-http` — uses `docker-compose.local.yml` (HTTP-only, no TLS, insecure
  dashboard bound to 127.0.0.1:8080). Drill/pilot only. Note: on `--local-http`
  hosts the recovery/update tooling now honors `docker-compose.local.yml`
  automatically (commits `2314014`, `99b8234`) — no manual override
  re-application is needed.
- `--allow-local-build` — explicitly allows a locally built image; requires
  `--odoo-image` to be an immutable `sha256` digest. Use for disposable pilots
  only.

### Step 5 — Add monitoring on the CommandCenter

```bash
/opt/kimkom-commandcenter/scripts/install-monitoring.sh \
    --client-slug <slug> --target-ts-ip <ts-ip>
```

Idempotent: adds node/postgres Prometheus targets and blackbox probes without
duplicating entries. Re-run any time to re-apply.

### Step 6 — Post-provisioning verification checklist (7 checks)

Run all seven after `install-monitoring.sh`:

1. **Compose healthy** — `ssh <user>@<ts-ip> 'cd /opt/kimkom-<slug> && docker compose -f docker-compose.yaml --env-file .env ps'` → all services `healthy`/`Up`
2. **HTTP 200** — on `--local-http`: `curl -H "Host: <domain>" http://<ts-ip>/` → 200
3. **Prometheus targets up** — both `client-nodes` (9100) and `client-postgres` (9187) report `up=1` on the CommandCenter
4. **DB modules ≥ 12** — `docker exec <odoo-container> odoo shell -d <db> --no-http -c 'print(len(env["ir.module.module"].search([("state","=","installed")])))'` (or psql `ir_module_module` count) → ≥ 12
5. **Backup pipeline** — 4 timers active (`kimkom-backup.timer`, `-retention`, `-check`, `-verify`) **and** `sudo /usr/local/libexec/kimkom-backup/backup.sh` exits 0 **and** `kimkom_backup_backup_last_run_success == 1` in Prometheus
6. **Recovery point** — `sudo /usr/local/libexec/kimkom-backup/recovery-point.sh create` succeeds and Odoo is healthy afterward (this is C3 pre-validation; applies on `--local-http` hosts too)
7. **Zero firing alerts** — `curl -sS http://127.0.0.1:9090/api/v1/alerts | jq '[.data.alerts[] | select(.state=="firing")] | length'` → 0

### Step 7 — Manual service additions

- **Portainer**: add the server at http://100.67.52.95:9000 → Environments →
  Add. Manual by design (phase `10-monitoring-onboard` prints the instructions;
  the Portainer agent must listen on `9001`).
- **GlitchTip project** (optional): create at http://100.67.52.95:8001 and pass
  the DSN via `--glitchtip-dsn` on provisioning (or add `GLITCHTIP_DSN` to the
  stack `.env` later).

### Known gaps (documented, not yet fixed in code)

- **Fresh private clone needs a per-customer GitHub deploy key** (Step 2). There
  is no shared-key fallback; a first-time deploy on a brand-new server cannot
  skip this.
- **S3 details must be confirmed per deploy**: bucket `<slug>-prod`, endpoint
  region (verify current Hetzner Object Storage docs — `.de` vs `.com`), and
  that `RESTIC_REPOSITORY` matches.
- **Portainer and GlitchTip onboarding have no automation** — manual by design.

---

## 5. Deploying Updates to Production

```bash
cd /opt/KimKom-stack
./update.sh --server <ip> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2 \
  --ssh-user alex --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key
```

This:
1. Creates a quiesced recovery point (stops Odoo, dumps DB + filestore together)
2. Fetches the target SHA
3. Pulls the exact image
4. Runs the module upgrade
5. Starts the new Odoo
6. Verifies image identity and health

**On failure:** Odoo stays stopped. Use the manual restore procedure in Section 6. There is NO automatic rollback.

**Compose-drift note:** on `--local-http` hosts, the update/recovery tooling
honors `docker-compose.local.yml` automatically (commits `2314014`, `99b8234`)
— no manual override re-application is needed after an update or restore.

---

## 6. Backups and Restore

### Routine backup (online, non-atomic)

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<ts-ip> 'sudo /usr/local/libexec/kimkom-backup/backup.sh'
```

Four timers run automatically:
- Hourly backup
- Daily retention
- Weekly check
- Monthly verify

### Manual restore after failed update

**Step 1 — Prepare** (non-destructive, validates the snapshot):

```bash
sudo /usr/local/libexec/kimkom-backup/restore-recovery-point.sh prepare --id <ID>
```

**Step 2 — Apply** (destructive, requires exact confirmation):

```bash
sudo /usr/local/libexec/kimkom-backup/restore-recovery-point.sh apply --id <ID> --confirm-id <ID>
```

This restores the paired DB+filestore plus the exact prior image and SHA. Odoo stays unavailable on failure.

**Apply notes (post-2026-07-30, re-verified 2026-08-02 drills):**
- `apply` runs `pg_terminate_backend()` before `dropdb` so postgres-exporter and other monitoring connections don't block the drop
- `apply` issues `--no-build` on the bring-up so locally-built images can be used without a registry
- `apply` pre-checks the prior image is present locally; if it is not (e.g. pruned), the apply refuses with a clear error
- The Odoo health check has a 600-second budget (raised from 300s after slow cold starts on low-memory VMs); on timeout it dumps container state, OOMKilled, and last 40 lines of logs
- The registry verification step uses `docker compose run --rm` (not `exec`) so the in-container `odoo --stop-after-init` does not conflict with the running Odoo process on port 8069
- **C3 S3 pre-validation** (`recovery-point.sh create` checks Restic S3 reachability before writing a recovery point) runs as part of verification checklist check 6 — confirmed working in the drills; on `--local-http` hosts the `docker-compose.local.yml` override is honored automatically

### CommandCenter backup

Daily Restic backup to a local repo. Timer at 00:01 UTC:

```bash
sudo ./scripts/backup-commandcenter.sh
```

---

## 7. Monitoring and Alerts

### Check Prometheus targets

```bash
curl -sS http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {instance: .labels.instance, health}'
```

### Check alerts

```bash
curl -sS http://127.0.0.1:9090/api/v1/alerts | jq '.data.alerts[] | {name: .labels.alertname, state}'
```

### Validate config

```bash
promtool check config monitoring/prometheus.yml
promtool check rules monitoring/prometheus/rules/baseline.yml
```

### Alertmanager

Generate config from template:

```bash
./scripts/generate-alertmanager-config.sh
```

Secrets are in `secrets/commandcenter/alertmanager-secrets` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). The generated config is untracked with mode `0644`. Restart after change:

```bash
docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager
```

### Alert rules

17 alert rules cover:
- Node, PostgreSQL, and HTTPS targets down
- Database too many connections
- Host disk low, memory low, swap pressure
- Backup failure or staleness
- Restore verification failure
- Managed dev container near memory limit or restarting

**Alert routing architecture (post-2026-07-30):**
- Critical availability rules (`ManagedNodeUnavailable`, `ManagedPostgreSQLUnavailable`, `ManagedHTTPSUnavailable`) match only `environment="production"`. Pilot targets (e.g. vranckeneers-prod TEST VM `environment="pilot"`) never trigger these.
- Alertmanager has a mute route for `environment != "production"` that catches any other alerts before they reach the Telegram critical route. The `mute` receiver is a no-op.
- All environment labels come from `monitoring/prometheus/targets/{nodes,postgres,http,https}.yml`. Set the label explicitly per target.

**Backup monitoring surface (post-rename, re-verified 2026-08-02):**
- Metric names are `kimkom_backup_*` (no `_v2_`): `kimkom_backup_backup_last_run_success`,
  `kimkom_backup_backup_last_success_timestamp_seconds`,
  `kimkom_backup_backup_last_duration_seconds`,
  `kimkom_backup_backup_last_completion_timestamp_seconds`,
  `kimkom_backup_verify_last_run_success`, `kimkom_backup_verify_last_success_timestamp_seconds`
- Grafana dashboard: **"Backup – Status"** (uid `kimkom-backup`), provisioned at
  `monitoring/grafana/provisioning/dashboards/backup.json`
- Alert rules in `monitoring/prometheus/rules/baseline.yml` reference the
  `kimkom_backup_*` names: `KimKomBackupFailed`, `KimKomBackupStale`,
  `KimKomBackupMetricsMissing`, `KimKomRestoreVerificationFailed`,
  `KimKomRestoreVerificationStale`

---

## 8. Module Development Workflow

1. Create the module under `/opt/kimkom-modules/<client-slug>/<module_name>/`
2. Dev containers mount this path read-only — test directly
3. Commit and push to the `kimkom-modules` repo
4. Deploy with `scripts/update-modules.sh` (rsync over Tailscale, recovery point, atomic swap, `odoo -u`)
5. CI image builds are manual-only (`workflow_dispatch`) — triggered for Odoo version bumps or Python dep changes

Enterprise, OCA, and shared modules are runtime mounts on the production server (`addons-enterprise/`, `addons-oca/` directories), not rsynced each update.

---

## 9. DNS and SSL

- **CommandCenter:** Cloudflare Tunnel routes `*.kimkom.net` to `192.168.178.19:80`. Traefik is HTTP-only — no Let's Encrypt on the controller.
- **Production:** Traefik auto-provisions Let's Encrypt. DNS must have A records for the domain and `*.domain`. Ports 80 and 443 must be open.
- **Pilots:** drill domains (e.g. the vranckeneers-prod drill) use `--local-http`
  and HTTP-only probes — no public DNS required. `kimkom-prod.kimkom.net`
  previously pointed at the TEST VM; the TEST VM currently hosts the
  vranckeneers-prod drill client.

---

## 10. Troubleshooting

### Instance won't start

- Check `.env` has `DB_PASSWORD`; always use `--env-file`
- Check PostgreSQL role: `docker exec odoo-postgres psql -U odoo -d postgres -c "\du"`
- Check `odoo.conf` mode: must be `0640` with group `101`, NOT `0600`
- Check filestore ownership: `chown -R 100:101 instances/<client>/data`

### Login rate limiting returns 404

- Traefik needs `--providers.file.directory=/etc/traefik/dynamic`
- Check `volumes/traefik/dynamic/login-rate-limit.yml` is mounted

### Prometheus target down

- Verify port is accessible from CommandCenter: `curl http://<ts-ip>:9100/metrics`
- Check target file format (valid YAML with `targets` and `labels`)
- Check UFW on target: allow from `100.67.52.95`

### Backup failure

- Check `/etc/kimkom-backup.env` exists and is `root:root 0600`
- Verify S3 credentials and Restic password files
- Check Restic repo: `sudo restic -r <repo> snapshots`

### Fresh-clone provisioning fails at git-clone (phase 01)

- Phase `01-git-clone` requires a **distinct per-customer GitHub deploy key**
  (`--github-deploy-key-file`). `install.sh` refuses to copy the CommandCenter
  deploy key, and a bare-repo/bundle workaround is drill-only.
- Generate `ssh-keygen -t ed25519 -f ~/.ssh/id_kimkom_github_<slug> -N ""`, add
  the `.pub` as a read-only Deploy key on the KimKom-stack GitHub repo, then
  re-run `init-client.sh` with `--resume --github-deploy-key-file ~/.ssh/id_kimkom_github_<slug>`.

### S3 / Restic repository mismatch

- `RESTIC_REPOSITORY` defaults to
  `s3:https://fsn1.your-objectstorage.com/<namespace>-prod`. If the bucket lives
  in another region or the Hetzner endpoint changed (verify `.de` vs `.com` in
  the current docs), set `RESTIC_REPOSITORY` explicitly as an env override.

### Portainer agent not connecting

- Agent must use `ports: "9001:9001"`, NOT `expose: 9001`
- UFW must allow port `9001` from the CommandCenter Tailscale IP

### Certificates

- Let's Encrypt rate limits: use the staging endpoint during initial testing
- Port 80 must be available for the HTTP-01 challenge
- Check Traefik logs: `docker logs commandcenter-traefik`

---

## 11. Credentials Reference

| Credential | Location | Permissions |
|---|---|---|
| PostgreSQL master password | `.env` | 0600 |
| Grafana admin | `.env` | 0600 |
| Portainer admin | `.env` | 0600 |
| GlitchTip admin | `glitchtip/.env` | 0600 |
| Instance DB passwords | `instances/<client>/.env` | 0640 |
| Deploy SSH key | `ssh/deploy_key` | 0600 |
| Per-customer GitHub deploy key (KimKom-stack clone) | `~/.ssh/id_kimkom_github_<slug>` (on CommandCenter) | 0600 |
| GlitchTip API token | `secrets/commandcenter/glitchtip-api-token` | 0600 |
| CommandCenter Restic password | `secrets/commandcenter/restic-password` | 0600 |
| Alertmanager secrets | `secrets/commandcenter/alertmanager-secrets` | 0600 |
| Prod S3 credentials | `/etc/kimkom-backup/aws-credentials` | root:root 0600 |
| Prod Restic password | `/etc/kimkom-backup/restic-password` | root:root 0600 |
| Prod backup config | `/etc/kimkom-backup.env` | root:root 0600 |
| Prod GlitchTip DSN | `$STACK_ROOT/.env` | 0600 |

---

## 12. Quick Reference

```bash
# Restart monitoring after config change
docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate prometheus
docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager

# View container logs
docker logs <container> --tail 50
docker logs --since 10m <container>

# List backup snapshots
ssh alex@100.114.91.105 'sudo restic -r s3:... snapshots'

# Check disk usage
df -h /
du -sh instances/*/data/

# Recreate dev instance
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --force-recreate --wait --wait-timeout 300

# Full validation checklist
promtool check config monitoring/prometheus.yml
promtool check rules monitoring/prometheus/rules/baseline.yml
curl -sS http://127.0.0.1:9090/api/v1/targets | jq '[.data.activeTargets[] | select(.health!="up")] | length'
curl -sS http://127.0.0.1:9090/api/v1/alerts | jq '[.data.alerts[] | select(.state=="firing")] | length'
curl -sS http://127.0.0.1:9093/-/healthy
curl -sS http://100.67.52.95:3000/api/health
docker exec odoo-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```
