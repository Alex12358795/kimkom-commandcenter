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
- **TEST VM** hosts the KimKom-stack at `/opt/kimkom-kimkom-prod`. Serves as the production pilot for the `kimkom-prod` customer.
- **Clients:**
  - SuperTCG (legacy)
  - Vranckeneers (legacy)
  - kimkom-dev (legacy)
  - kimkom-prod (TEST pilot)
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

### Prerequisites

- Dedicated server with Ubuntu and Docker installed
- GitHub deploy key for KimKom-stack (if private repo clone is needed)
- DNS: domain and `*.domain` pointing to the server IP
- S3 bucket credentials for backups
- Tailscale auth key
- Odoo image from GHCR: `ghcr.io/alex12358795/kimkom-prod-odoo@sha256:...`
- Off-host backup escrow reference

### Step 1 — Provision from the controller (clean checkout required)

```bash
cd /opt/KimKom-stack
./init-client.sh --server <public-ip> --client "Customer Name" --client-slug <slug> \
  --domain <domain> --odoo-image <image@sha256:digest> \
  --backup-s3-key <key> --backup-s3-secret <secret> \
  --backup-escrow-reference <off-host-ref> --tailscale-token <tskey>
```

### Step 2 — Add Prometheus targets on CommandCenter

After provisioning completes, run:

```bash
/opt/kimkom-commandcenter/scripts/install-monitoring.sh \
    --client-slug <slug> --target-ts-ip <ts-ip>
```

### Step 3 — Add server to Portainer

Manually add the server at http://100.67.52.95:9000 → Environments → Add.

### Step 4 — Create a GlitchTip project

Create a GlitchTip project for the customer at http://100.67.52.95:8001.

### Provisioning phases

`server-bootstrap`, `git-clone`, `tailscale`, `directories`, `env-setup`, `dns-preflight`, `odoo-init`, `full-stack`, `health-check`, `backup-setup`, `monitoring-onboard`.

### Flags

- `--resume` — continue a failed run
- `--force-phase <name>` — re-run a single phase
- `--reset-state` — clear provisioning state
- `--glitchtip-dsn <dsn>` — supply a GlitchTip DSN
- `--github-deploy-key-file <path>` — GitHub deploy key for private repo clone
- `--tailscale-token <key>` — Tailscale auth key
- `--commandcenter-ip <ip>` — CommandCenter Tailscale IP

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

---

## 6. Backups and Restore

### Routine backup (online, non-atomic)

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<ts-ip> 'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'
```

Four timers run automatically:
- Hourly backup
- Daily retention
- Weekly check
- Monthly verify

### Manual restore after failed update

**Step 1 — Prepare** (non-destructive, validates the snapshot):

```bash
sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh prepare --id <ID>
```

**Step 2 — Apply** (destructive, requires exact confirmation):

```bash
sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh apply --id <ID> --confirm-id <ID>
```

This restores the paired DB+filestore plus the exact prior image and SHA. Odoo stays unavailable on failure.

**Apply notes (post-2026-07-30):**
- `apply` runs `pg_terminate_backend()` before `dropdb` so postgres-exporter and other monitoring connections don't block the drop
- `apply` issues `--no-build` on the bring-up so locally-built images can be used without a registry
- `apply` pre-checks the prior image is present locally; if it is not (e.g. pruned), the apply refuses with a clear error
- The Odoo health check has a 600-second budget (raised from 300s after slow cold starts on low-memory VMs); on timeout it dumps container state, OOMKilled, and last 40 lines of logs
- The registry verification step uses `docker compose run --rm` (not `exec`) so the in-container `odoo --stop-after-init` does not conflict with the running Odoo process on port 8069

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
- Critical availability rules (`ManagedNodeUnavailable`, `ManagedPostgreSQLUnavailable`, `ManagedHTTPSUnavailable`) match only `environment="production"`. Pilot targets (e.g. kimkom-prod TEST VM `environment="pilot"`) never trigger these.
- Alertmanager has a mute route for `environment != "production"` that catches any other alerts before they reach the Telegram critical route. The `mute` receiver is a no-op.
- All environment labels come from `monitoring/prometheus/targets/{nodes,postgres,http,https}.yml`. Set the label explicitly per target.

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
- **kimkom-prod.kimkom.net** currently points to the TEST VM at `192.168.178.20`.

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

- Check `/etc/kimkom-backup-v2.env` exists and is `root:root 0600`
- Verify S3 credentials and Restic password files
- Check Restic repo: `sudo restic -r <repo> snapshots`

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
| GlitchTip API token | `secrets/commandcenter/glitchtip-api-token` | 0600 |
| CommandCenter Restic password | `secrets/commandcenter/restic-password` | 0600 |
| Alertmanager secrets | `secrets/commandcenter/alertmanager-secrets` | 0600 |
| Prod S3 credentials | `/etc/kimkom-backup-v2/aws-credentials` | root:root 0600 |
| Prod Restic password | `/etc/kimkom-backup-v2/restic-password` | root:root 0600 |
| Prod backup config | `/etc/kimkom-backup-v2.env` | root:root 0600 |
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
