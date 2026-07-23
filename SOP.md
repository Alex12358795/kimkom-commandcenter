# KimKom — Standard Operating Procedures

Step-by-step instructions for day-to-day operations: adding clients, developing modules, deploying to production, upgrades, rollbacks, and disaster recovery.

---

## Table of Contents

1. [Infrastructure Overview](#1-infrastructure-overview)
2. [Adding a New Development Client](#2-adding-a-new-development-client)
3. [Developing Odoo Modules](#3-developing-odoo-modules)
4. [Pushing Modules to GitHub](#4-pushing-modules-to-github)
5. [Building a Production Image (CI)](#5-building-a-production-image-ci)
6. [Provisioning a New Production Customer](#6-provisioning-a-new-production-customer)
7. [Deploying a Production Update](#7-deploying-a-production-update)
8. [Rolling Back a Production Deployment](#8-rolling-back-a-production-deployment)
9. [Running Backups](#9-running-backups)
10. [Restoring from Backup](#10-restoring-from-backup)
11. [Connecting GlitchTip to an Instance](#11-connecting-glitchtip-to-an-instance)
12. [Monitoring and Alerting](#12-monitoring-and-alerting)
13. [Troubleshooting](#13-troubleshooting)
14. [Credentials and Secrets Reference](#14-credentials-and-secrets-reference)

---

## 1. Infrastructure Overview

```
Your Workstation
    ↓ SSH (deploy_key)
    ↓
CommandCenter (192.168.178.19 / 100.67.52.95)
    ├── Traefik reverse proxy (port 80)
    ├── PostgreSQL 17 (shared, port 5432)
    ├── Prometheus + Grafana + Alertmanager + Loki
    ├── GlitchTip (error tracking)
    ├── Portainer CE (container management)
    ├── Dev Odoo instances: SuperTCG, Vranckeneers, kimkom-dev
    └── Daily backup to local Restic repo
    ↓
    ↓ git push (from modules/) → GitHub
    ↓ CI → builds image → GHCR
    ↓
    ↓ SSH (deploy_key) → update.sh → pulls new image
    ↓
PROD VM (Hetzner, one per customer)
    ├── Tailscale (100.x.x.x, RouteAll=false, CorpDNS=false)
    ├── Traefik (80/443) + Let's Encrypt
    ├── Odoo 18 + PostgreSQL 17
    ├── Prometheus exporters (Tailscale-only)
    ├── Portainer Agent (Tailscale-only)
    └── Backup-v2 (hourly, H3 S3)
```

**Repositories:**
- `Alex12358795/kimkom-commandcenter` — this machine
- `Alex12358795/KimKom-stack` — production deployment scripts
- `Alex12358795/kimkom-modules` — shared + per-client Odoo modules

---

## 2. Adding a New Development Client

A dev client is a new Odoo instance on CommandCenter for development and testing.

### 2.1 Create the instance

```bash
cd /opt/kimkom-commandcenter
./scripts/create-odoo-instance.sh --client Acme
```

This creates:
- `instances/acme/` directory
- `instances/acme/docker-compose.yml` (Traefik labels, rate limiting, WebSocket)
- `instances/acme/config/odoo.conf` (dedicated DB role, sentry_dsn)
- `instances/acme/.env` (DB_PASSWORD, ODOO_ADMIN_PASSWORD, GLITCHTIP_DSN)
- `instances/acme/Dockerfile` (with sentry-sdk>=2.0.0)
- `instances/acme/addons/` — empty, add your modules here
- `instances/acme/addons-oca/` — empty, copy OCA modules here
- `instances/acme/data/` — filestore, chown 100:101
- Dedicated PostgreSQL role `odoo_acme` and database `odoo_acme`
- Odoo MCP config entry

### 2.2 Start the instance

```bash
docker compose -f instances/acme/docker-compose.yml --env-file instances/acme/.env up -d --build --wait --wait-timeout 300
```

### 2.3 Verify

```bash
# Check container health
docker ps --filter name=odoo-acme

# Check login page (adjust hostname to your DNS/Cloudflare setup)
curl -sS -o /dev/null -w '%{http_code}' https://acme.kimkom.net/web/login
```

### 2.4 Add Cloudflare Tunnel route

In your Proxmox Cloudflare Tunnel config, add:
```
public_hostname: acme.kimkom.net → http://192.168.178.19:80
```

### 2.5 Connect GlitchTip

See [Section 11](#11-connecting-glitchtip-to-an-instance).

### 2.6 Copy OCA modules (if needed)

```bash
# From existing instance (e.g., sentry module)
cp -r instances/SuperTCG/addons-oca/sentry instances/acme/addons-oca/
```

---

## 3. Developing Odoo Modules

### 3.1 Find where the modules live

Dev instances mount their addons directories as writable bind mounts:

| Mount | Path on host | Contents |
|---|---|---|
| `/mnt/extra-addons` | `instances/<client>/addons/` | Custom modules you develop |
| `/mnt/extra-enterprise` | `instances/<client>/addons-enterprise/` | Odoo Enterprise (not committed) |
| `/mnt/extra-oca` | `instances/<client>/addons-oca/` | OCA community modules (not committed) |

### 3.2 Create a new module

```bash
cd /opt/kimkom-commandcenter/instances/<client>/addons/
mkdir my_module
cd my_module
```

Create the minimum files:
```
my_module/
  __init__.py          # from . import models
  __manifest__.py      # { "name": "My Module", "version": "18.0.1.0.0", ... }
  models/
    __init__.py         # from . import my_model
    my_model.py          # class MyModel(models.Model): ...
```

### 3.3 Install the module

```bash
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env \
  run --rm odoo -- -i my_module --stop-after-init --no-http
```

### 3.4 Upgrade the module after changes

```bash
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env \
  run --rm odoo -- -u my_module --stop-after-init --no-http
```

### 3.5 Run module tests

```bash
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env \
  run --rm odoo -- --test-enable --log-level=test --stop-after-init -i my_module
```

### 3.6 View logs

```bash
docker logs -f odoo-<client>
# Or via Grafana → Explore → Loki → {container_name="odoo-<client>"}
```

### 3.7 Access the Odoo shell

```bash
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env \
  run --rm odoo odoo shell -d odoo<Client>
```

---

## 4. Pushing Modules to GitHub

### 4.1 Directory structure in kimkom-modules

```
/opt/kimkom-modules/
  shared/                    # Modules used by all clients
  <client-slug>/             # Modules for one specific client
```

### 4.2 Before you start

```bash
cd /opt/kimkom-modules
git pull origin main   # Get latest
```

### 4.3 Copy your modules from the dev instance

```bash
# For client-specific modules:
cp -r /opt/kimkom-commandcenter/instances/<client>/addons/my_module /opt/kimkom-modules/<client-slug>/

# For shared modules:
cp -r /opt/kimkom-commandcenter/instances/<client>/addons/kimkom_shared_module /opt/kimkom-modules/shared/
```

### 4.4 Clean up before committing

```bash
cd /opt/kimkom-modules/<client-slug>/my_module
rm -rf __pycache__/ *.pyc   # Remove compiled Python
```

### 4.5 Commit and push

```bash
cd /opt/kimkom-modules
git add -A
git status                   # Verify what you're committing
git commit -m "feat(<client>): add my_module — brief description"
git push origin main
```

### 4.6 Update the client manifest (if new OCA/Enterprise deps)

Edit `/opt/KimKom-stack/clients/<client-slug>.yml`:

```yaml
modules:
  shared:
    - kimkom_shared_module
  client_dir: "<client-slug>"
  oca:
    - repo: "https://github.com/OCA/server-tools.git"
      ref: "18.0"
      modules: ["sentry", "auditlog"]
```

Commit and push KimKom-stack:

```bash
cd /opt/KimKom-stack
git commit -am "chore(<client>): update module manifest"
git push origin main
```

### 4.7 Verify CI

CI will automatically:
1. Validate manifests
2. Checkout modules at the pinned commit
3. Run Odoo lint + tests
4. Build the image
5. Scan with Trivy
6. Push to GHCR

Check at: `https://github.com/Alex12358795/KimKom-stack/actions`

---

## 5. Building a Production Image (CI)

The CI pipeline (`immutable-image.yml`) builds automatically on push to `main` or when manually triggered.

### 5.1 How it works

1. Validate client manifests + shell syntax + Compose configs
2. For each client in the manifest matrix:
   - Checkout `kimkom-modules` at pinned commit
   - Checkout OCA repos at pinned refs
   - Copy modules into `odoo/modules/<client-slug>/`
   - Run `odoo -i base --stop-after-init` (lint)
   - Run `odoo --test-enable --log-level=test` (tests)
3. Build Docker image with `CLIENT_SLUG` build arg
4. Scan with Trivy (CRITICAL, HIGH)
5. Push to GHCR as `ghcr.io/alex12358795/<slug>-odoo:<git-sha>`

### 5.2 Manually trigger CI

1. Go to `https://github.com/Alex12358795/KimKom-stack/actions`
2. Click "Immutable image CI"
3. Click "Run workflow"
4. Select branch: `main`
5. Click "Run workflow"

### 5.3 Get the image digest

After CI succeeds, get the digest:

```bash
docker pull ghcr.io/alex12358795/<slug>-odoo:<git-sha>
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/alex12358795/<slug>-odoo:<git-sha>
```

Use the `@sha256:...` value as `--odoo-image` in `init-client.sh` or in the `.env` on the production server.

---

## 6. Provisioning a New Production Customer

This is the complete zero-to-live workflow. Follow every step in order.

### 6.0 Before You Start — Complete Checklist

Before running any commands, collect these:

| Item | Required? | Where to get it |
|---|---|---|
| Customer display name | Yes | Client provides |
| Customer slug (lowercase, DNS-safe) | Yes | Set yourself (e.g., `acme`) |
| Production domain | Yes | Client provides (e.g., `acme.com`) |
| Hetzner VPS (or similar) | Yes | Fresh Ubuntu 24.04, at least 2 vCPU, 4 GB RAM, 40 GB disk |
| VPS public IP | Yes | From VPS provider console |
| VPS root password or user | Yes | From VPS provider |
| SSH key for VPS | Yes | Usually VPS provider adds one; we add our deploy key too |
| DNS A record | Yes | `<domain>` → VPS public IP (create before TLS phase) |
| Hetzner Object Storage bucket | Yes | Create via Hetzner Cloud Console |
| S3 access key + secret (for backups) | Yes | Create via Hetzner Cloud Console → Object Storage → Credentials |
| Tailscale auth key | **Recommended** | https://login.tailscale.com/admin/settings/keys (one-time key) |
| Odoo image digest | Yes | From CI pipeline (see Section 5.3) — `ghcr.io/alex12358795/<slug>-odoo@sha256:...` |
| GlitchTip DSN | **Recommended** | Create project first (see Section 11.1) — store the DSN |
| Module manifest | Yes | `clients/<slug>.yml` in KimKom-stack (see Section 6.1 below) |
| Modules ready in kimkom-modules repo | Yes | All customer + shared modules pushed to GitHub |
| Backup Restic password | Yes | Generate and escrow: `openssl rand -base64 32` |
| Enterprise modules (optional) | If licensed | Exact commit SHA from Odoo's private repo |
| OCA modules (optional) | If needed | Exact commit SHAs per repo |

### 6.1 Create Module Space

```bash
# Customer-specific modules
mkdir -p /opt/kimkom-modules/<client-slug>

# If they use shared KimKom modules, ensure they're in /opt/kimkom-modules/shared/

# Copy your dev modules in (if already developed)
cp -r /opt/kimkom-commandcenter/instances/<client>/addons/* /opt/kimkom-modules/<client-slug>/

# Clean up
find /opt/kimkom-modules/<client-slug> -name '__pycache__' -exec rm -rf {} + 2>/dev/null
find /opt/kimkom-modules/<client-slug> -name '*.pyc' -delete 2>/dev/null
find /opt/kimkom-modules/<client-slug> -name '.git' -exec rm -rf {} + 2>/dev/null

# Commit and push
cd /opt/kimkom-modules
git add -A
git status
git commit -m "feat(<client-slug>): initial client modules"
git push origin main
```

Note the **exact commit SHA** that was pushed — you'll need this for the manifest:
```bash
git rev-parse HEAD  # e.g., a3c50167b58ced55cf1502c4f7efbdf25845bf3c
```

### 6.2 Create the Client Manifest

Create `/opt/KimKom-stack/clients/<client-slug>.yml`:

```yaml
{
  "schema_version": 2,
  "display_name": "Acme Corp",
  "slug": "acme",
  "profiles": ["core"],
  "target_rpo": "1h",
  "target_rto": "4h",
  "image": {
    "repository": "ghcr.io/alex12358795/acme-odoo",
    "tag": "<git-sha>"
  },
  "management": {
    "provider": "tailscale",
    "resource_id": "acme"
  },
  "network": {
    "provider": "tailscale",
    "public_address": null,
    "private_address": null
  },
  "modules": {
    "kimkom_modules_repo": "git@github.com:Alex12358795/kimkom-modules.git",
    "kimkom_modules_ref": "a3c50167b58ced55cf1502c4f7efbdf25845bf3c",
    "shared": [],
    "client_dir": "acme",
    "enterprise": null,
    "oca": [
      {
        "repo": "https://github.com/OCA/server-tools.git",
        "ref": "abc123...",
        "modules": ["sentry"]
      }
    ],
    "external": []
  }
}
```

**IMPORTANT:** Use exact commit SHAs for `kimkom_modules_ref` and OCA `ref` values — NOT branch names like `main` or `18.0`. Production images must be reproducible.

Validate the manifest:
```bash
cd /opt/KimKom-stack
python3 scripts/ci/validate-client-manifests.py
```

Commit and push:
```bash
cd /opt/KimKom-stack
git add clients/<client-slug>.yml
git commit -m "feat(<client-slug>): add client manifest"
git push origin main
```

### 6.3 Build the Release Image

Wait for CI to complete (or trigger it manually):
1. Go to `https://github.com/Alex12358795/KimKom-stack/actions`
2. Click "Immutable image CI" → "Run workflow"
3. Wait for the `image` job to complete
4. Get the image digest from the CI logs, or:

```bash
# After CI push:
docker pull ghcr.io/alex12358795/<slug>-odoo:<git-sha>
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/alex12358795/<slug>-odoo:<git-sha>
# Output: ghcr.io/alex12358795/acme-odoo@sha256:abc123...
```

Copy this full digest — you'll pass it as `--odoo-image`.

### 6.4 Prepare the VPS

Create the VPS with the VPS provider. Once booted:

1. **Add deploy key**: Log in and add our deploy key
```bash
# If you have root access:
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOuWELPp5kpEHCTjqQhJ9HNXsGjf5QMsm6OnLdEqeM9+ kimkom-deploy' >> ~/.ssh/authorized_keys

# Also add the ~/.ssh/id_ed25519 key if needed for the init flow
```

2. **Verify SSH**: From CommandCenter:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key root@<VPS_IP> 'echo OK'
```

3. **Create DNS A record**: Point `<domain>` to the VPS public IP (do this before the TLS phase or Let's Encrypt will fail)

### 6.5 Create GlitchTip Project

```bash
TOKEN=$(cat /opt/kimkom-commandcenter/secrets/commandcenter/glitchtip-api-token)

# Create project
curl -sS -X POST http://100.67.52.95:8001/api/0/teams/kimkom/kimkom/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"<client-slug>","slug":"<client-slug>"}'

# Get DSN
curl -sS http://100.67.52.95:8001/api/0/projects/kimkom/<client-slug>/keys/ \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
keys=json.load(sys.stdin)
print(keys[0]['dsn']['public'])
"
```

Copy the DSN — you'll use it as `--glitchtip-dsn`.

### 6.6 Provision the Server

```bash
cd /opt/KimKom-stack

./init-client.sh \
  --server <VPS_PUBLIC_IP> \
  --client "Acme Corp" \
  --client-slug acme \
  --domain acme.com \
  --odoo-image "ghcr.io/alex12358795/acme-odoo@sha256:abc123..." \
  --backup-s3-key "ACME_BACKUP_KEY" \
  --backup-s3-secret "ACME_BACKUP_SECRET" \
  --tailscale-token "tskey-auth-xxx" \
  --glitchtip-dsn "http://xxx@100.67.52.95:8001/6" \
  --commandcenter-ip "100.67.52.95" \
  --ssh-user root \
  --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key \
  --resume
```

This will run all 11 phases. The script is resumable — if anything fails, just re-run with `--resume`.

### 6.7 Post-Provisioning Manual Steps

1. **Portainer enrollment**: `http://100.67.52.95:9000` → Environments → Add → Docker Agent → `<tailscale-ip>:9001`
2. **Verify HTTPS**: `curl -I https://<domain>` (should show valid Let's Encrypt cert)
3. **Verify WebSocket**: `curl -sS -o /dev/null -w "%{http_code}" https://<domain>/websocket -H "Upgrade: websocket" -H "Connection: Upgrade" -H "Sec-WebSocket-Key: test==" -H "Sec-WebSocket-Version: 13"` (expect 101)
4. **Verify login disabled**: `curl -sS https://<domain>/web/database/manager` (should show "disabled")
5. **Test backup**: SSH to server and run:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env /opt/kimkom-<slug>/scripts/backup-v2/backup.sh'
```
6. **Verify restore**: 
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env /opt/kimkom-<slug>/scripts/backup-v2/verify-restore.sh'
```
7. **Test Telegram alert**: The Alertmanager test message was sent earlier; verify you received it
8. **Verify GlitchTip**: Trigger a test exception in Odoo, check GlitchTip receives it

### 6.8 Acceptance Checklist

Before handing over to the customer:

```text
[ ] Public HTTPS login returns 200
[ ] SSL certificate is valid (not self-signed, no -k needed)
[ ] WebSocket returns 101
[ ] Database manager is disabled
[ ] list_db = False
[ ] dbfilter is set correctly
[ ] Dedicated PostgreSQL role exists (not shared superuser)
[ ] Odoo image matches expected digest
[ ] GlitchTip receives test exceptions
[ ] Prometheus targets are up and green
[ ] Telegram alert was received (test message sent during setup)
[ ] Portainer endpoint is enrolled
[ ] Online backup completes successfully
[ ] Isolated restore verification passes
[ ] Restic password is stored off-host (not only on the server)
[ ] Deployed Git SHA and image digest are recorded
[ ] Cloudflare DNS A record is set
[ ] Customer has admin credentials (from .env on the server)
```

### 6.9 Record the Deployment

Store this information in a secure location:
- Server IP + Tailscale IP
- Domain + DNS provider
- Image digest deployed
- Git SHA deployed
- PostgreSQL role + database name
- S3 bucket name + backup credentials
- Restic password
- GlitchTip DSN
- Grafana / Portainer / GlitchTip URLs (Tailscale-only)

To start completely over:

```bash
./init-client.sh ... --reset-state
```

### 6.4 Post-provisioning manual steps

1. **Portainer**: Go to `http://100.67.52.95:9000` → Environments → Add → Docker Agent → `<tailscale-ip>:9001`
2. **Cloudflare DNS**: Ensure the domain's A record points to the VPS public IP
3. **Verify SSL**: `curl -I https://<domain>`
4. **Test backup**: `ssh ... sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env ... scripts/backup-v2/backup.sh`

---

## 7. Deploying a Production Update

### 7.1 Standard update (pull latest stack, redeploy)

```bash
cd /opt/KimKom-stack
./update.sh \
  --server <tailscale-ip> \
  --client-slug <slug> \
  --ssh-user alex \
  --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key
```

This does:
1. `git fetch` the latest commit on `main`
2. Compose diff — shows which services changed
3. `git pull` to the target ref
4. `docker compose up -d` on only the changed services
5. Health check

### 7.2 Deploy a specific Git commit

```bash
./update.sh \
  --server <tailscale-ip> \
  --client-slug <slug> \
  --ref <commit-sha> \
  --ssh-user alex \
  --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key
```

### 7.3 Update only the Odoo image (pin new digest)

1. Update the digest on the production server:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip>
cd /opt/kimkom-<slug>
sed -i 's|ODOO_IMAGE=.*|ODOO_IMAGE=ghcr.io/alex12358795/<slug>-odoo@sha256:...|' .env
```

2. Run the deployment script:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'cd /opt/kimkom-<slug> && sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env scripts/backup-v2/backup.sh'
```

3. Pull and restart:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'cd /opt/kimkom-<slug> && docker compose pull odoo && docker compose up -d --wait --wait-timeout 180 odoo'
```

### 7.4 Update Odoo modules (database upgrade)

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip>
cd /opt/kimkom-<slug>

# Backup first — ALWAYS
sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env scripts/backup-v2/backup.sh

# Install new modules or upgrade existing ones
docker compose run --rm odoo -- -u module1,module2 --stop-after-init --no-http

# Or install new modules
docker compose run --rm odoo -- -i new_module --stop-after-init --no-http

# Restart to pick up registry changes
docker compose up -d --wait --wait-timeout 180 odoo
```

### 7.5 Restart a single service

```bash
./update.sh --server <ip> --client-slug <slug> --restart <service-name>
```

---

## 8. Rolling Back a Production Deployment

### 8.1 Roll back code/image (safe — no database changes)

If you only changed the Odoo image or configuration (no module upgrades):

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip>
cd /opt/kimkom-<slug>

# Revert .env to the previous image digest
vim .env   # or sed replacement

# Or revert git to the previous commit
git log --oneline -5
git reset --hard <previous-commit>

# Rebuild/pull and restart
docker compose pull odoo        # if using registry image
docker compose build odoo       # if building locally
docker compose up -d --wait --wait-timeout 180 odoo
```

### 8.2 Roll back after module upgrade (DANGER — database already changed)

**Image rollback alone is NOT sufficient.** Module upgrades execute database migrations that are forward-only.

For a full rollback after module upgrade:
1. Stop Odoo: `docker compose stop odoo`
2. Restore the pre-upgrade backup:
```bash
sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env \
  restic restore <snapshot-id> --target /var/lib/kimkom-backup-v2/restore
# Then drop the database, recreate it, and pg_restore from the backup dump
```
3. Revert code to pre-upgrade state
4. Start Odoo
5. Run `-u` on base modules to rebuild the registry

**Rule:** Always take a backup BEFORE any module upgrade.

---

## 9. Running Backups

### 9.1 CommandCenter backup (daily, automatic)

Runs via systemd timer. Check status:

```bash
systemctl status kimkom-backup-cc.timer
systemctl list-timers kimkom-backup-cc
```

Manual run:

```bash
cd /opt/kimkom-commandcenter
sudo ./scripts/backup-commandcenter.sh
```

View snapshots:

```bash
restic snapshots --repo local:backup-repo --password-file secrets/commandcenter/restic-password
```

### 9.2 Production backup (hourly, automatic)

Runs via systemd timers. Check on production server:

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip>
systemctl status kimkom-backup-v2.timer
```

Manual run:

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env \
  /opt/kimkom-<slug>/scripts/backup-v2/backup.sh'
```

Manual restore verification (monthly automatic):

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env \
  /opt/kimkom-<slug>/scripts/backup-v2/verify-restore.sh'
```

View snapshots:

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo bash -c "set -a; source /etc/kimkom-backup-v2.env; set +a; restic snapshots"'
```

---

## 10. Restoring from Backup

### 10.1 CommandCenter restore

```bash
cd /opt/kimkom-commandcenter

# List snapshots
restic snapshots --repo local:backup-repo --password-file secrets/commandcenter/restic-password

# Restore latest to a temporary directory
restic restore latest --repo local:backup-repo --password-file secrets/commandcenter/restic-password --target /tmp/cc-restore

# Restore specific snapshot
restic restore <snapshot-id> --repo local:backup-repo --password-file secrets/commandcenter/restic-password --target /tmp/cc-restore
```

### 10.2 Production restore

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip>

# List snapshots
sudo bash -c 'set -a; source /etc/kimkom-backup-v2.env; set +a; restic snapshots'

# Restore a snapshot
sudo bash -c 'set -a; source /etc/kimkom-backup-v2.env; set +a; restic restore <snapshot-id> --target /tmp/prod-restore'

# The snapshot contains:
#   - odoo.dump (pg_dump -Fc format)
#   - release-manifest.tsv
#   - Odoo filestore
```

To fully restore a production database:
1. Stop Odoo: `docker compose stop odoo`
2. Drop the database: `docker compose exec odoo-db dropdb -U odoo odoo`
3. Create fresh: `docker compose exec odoo-db createdb -U odoo odoo`
4. Restore: `docker compose exec -T odoo-db pg_restore -U odoo -d odoo < /tmp/prod-restore/odoo.dump`
5. Restore filestore: `sudo cp -a /tmp/prod-restore/filestore/. volumes/odoo/filestore/`
6. Fix permissions: `sudo chown -R 100:101 volumes/odoo/filestore`
7. Start Odoo: `docker compose up -d odoo`

---

## 11. Connecting GlitchTip to an Instance

### 11.1 Create a GlitchTip project

```bash
TOKEN=$(cat /opt/kimkom-commandcenter/secrets/commandcenter/glitchtip-api-token)

# Create project
curl -sS -X POST http://100.67.52.95:8001/api/0/teams/kimkom/kimkom/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"<client-slug>","slug":"<client-slug>"}'

# Get the DSN
curl -sS http://100.67.52.95:8001/api/0/projects/kimkom/<client-slug>/keys/ \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
keys=json.load(sys.stdin)
print(keys[0]['dsn']['public'])
"
```

### 11.2 Configure the dev instance

Edit `instances/<client>/config/odoo.conf` — add at the bottom:

```ini
sentry_enabled = True
sentry_dsn = http://<public-key>@100.67.52.95:8001/<project-id>
sentry_environment = development
sentry_server_name = <ClientName>
```

### 11.3 Ensure sentry-sdk is installed

Check `instances/<client>/Dockerfile` has:
```
RUN pip3 install ... sentry-sdk>=2.0.0
```

### 11.4 Copy the sentry OCA module

```bash
cp -r /opt/kimkom-commandcenter/instances/SuperTCG/addons-oca/sentry \
  /opt/kimkom-commandcenter/instances/<client>/addons-oca/
```

### 11.5 Rebuild and install

```bash
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env build --no-cache odoo
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --force-recreate --wait --wait-timeout 300
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env run --rm odoo -- -i sentry --stop-after-init --no-http
docker compose -f instances/<client>/docker-compose.yml --env-file instances/<client>/.env up -d --wait --wait-timeout 300
```

### 11.6 Verify

Check GlitchTip for new events at `http://100.67.52.95:8001`.

---

## 12. Monitoring and Alerting

### 12.1 Access Grafana

```
http://100.67.52.95:3000  (Tailscale only)
Login: admin / password in /opt/kimkom-commandcenter/.env (GRAFANA_PASSWORD)
```

### 12.2 Available dashboards

| Dashboard | What it shows |
|---|---|
| KimKom – Customer Overview | Uptime, response time, DB connections, alerts, backup status, disk/memory, SSL expiry |
| Node Exporter | CPU, memory, disk, network per server |
| PostgreSQL | DB connections, transactions, cache hit ratio |
| Backup v2 – Status | Backup success/fail, last backup age, restore verification |

### 12.3 Check alerts

```bash
# Current firing alerts
curl -sS http://127.0.0.1:9090/api/v1/alerts | python3 -c "
import sys,json
alerts = [a for a in json.load(sys.stdin)['data']['alerts'] if a['state'] == 'firing']
for a in alerts: print(f\"{a['labels']['alertname']}: {a['annotations'].get('summary','')}\")
"
# If no output, no alerts are firing
```

### 12.4 Check Prometheus targets

```bash
curl -sS http://127.0.0.1:9090/api/v1/targets | python3 -c "
import sys,json
targets = json.load(sys.stdin)['data']['activeTargets']
bad = [t for t in targets if t['health'] != 'up']
if bad:
    for t in bad: print(f\"DOWN: {t['labels']['job']} ({t['labels'].get('instance','?')})\")
else:
    print('All targets up')
"
```

### 12.5 Add Prometheus targets for a new production server

Edit `/opt/kimkom-commandcenter/monitoring/prometheus/targets/nodes.yml`:
```yaml
- <tailscale-ip>:9100
```

Edit `/opt/kimkom-commandcenter/monitoring/prometheus/targets/postgres.yml`:
```yaml
- <tailscale-ip>:9187
```

Edit `/opt/kimkom-commandcenter/monitoring/blackbox/targets/https.yml`:
```yaml
- <domain>
```

Restart Prometheus:
```bash
docker compose -f monitoring/docker-compose.yml --env-file .env restart prometheus
```

### 12.6 Search logs in Loki

1. Open Grafana → Explore
2. Select datasource: `Loki`
3. Query examples:
   - `{container_name="odoo-supertcg"}` — all logs from SuperTCG
   - `{container_name=~"odoo-.*"} |= "ERROR"` — errors from any Odoo container
   - `{container_name="odoo-postgres"}` — PostgreSQL logs

---

## 13. Troubleshooting

### 13.1 Odoo won't start — "Database connection failure"

```bash
# Check PostgreSQL role exists
docker exec odoo-postgres psql -U odoo -d odoomaster -c "\du"

# If missing, create it:
docker exec odoo-postgres psql -U odoo -d odoomaster -c \
  "CREATE ROLE odoo_<slug> WITH LOGIN PASSWORD '<password>';"

# Check DB exists
docker exec odoo-postgres psql -U odoo -d odoomaster -l

# Check .env password matches the role
cat instances/<client>/.env | grep DB_PASSWORD
cat instances/<client>/config/odoo.conf | grep db_password

# Check odoo.conf is readable by container (group 101, mode 640)
ls -la instances/<client>/config/odoo.conf
# Should be: -rw-r----- 1 alex lxd
```

### 13.2 Odoo shows "The database manager has been disabled"

Good — this is intentional. `list_db = False` in `odoo.conf`.

### 13.3 404 on public hostname

```bash
# Check Traefik router config
docker logs commandcenter-traefik 2>&1 | grep -i "<hostname>"

# Check Traefik labels
grep traefik instances/<client>/docker-compose.yml

# Check Traefik dynamic config is mounted
docker inspect commandcenter-traefik --format '{{range .Mounts}}{{.Source}} → {{.Destination}}{{"\n"}}{{end}}'

# Should show: /opt/kimkom-commandcenter/volumes/traefik/dynamic → /etc/traefik/dynamic
```

### 13.4 Prometheus target down

```bash
# Check if exporter is running on target
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'docker ps --filter name=node-exporter && curl -s localhost:9100/metrics | head -3'

# Check UFW allows CommandCenter access
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo ufw status | grep -E "9100|9187"'
```

### 13.5 Promtail "Unable to refresh target groups"

Promtail needs the Docker socket. Check:
```bash
docker inspect odoo-promtail --format '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}Docker socket mounted{{end}}{{end}}'
```

If missing: the monitoring `docker-compose.yml` should have:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

### 13.6 Alertmanager "permission denied" on config

```bash
chmod 644 /opt/kimkom-commandcenter/monitoring/alertmanager/alertmanager.yml
docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager
```

### 13.7 GlitchTip not receiving events

```bash
# Check sentry module is installed
docker exec odoo-<client> python3 -c "import sentry_sdk; print('OK')"

# Check sentry_dsn in odoo.conf
docker exec odoo-<client> grep sentry_dsn /etc/odoo/odoo.conf

# Check GlitchTip is reachable from container
docker exec odoo-<client> curl -I http://100.67.52.95:8001
```

### 13.8 Grafana dashboard empty or "No data"

```bash
# Check Prometheus data source UID matches dashboard
curl -sS -u admin:<password> http://100.67.52.95:3000/api/datasources | python3 -c "
import sys,json
for ds in json.load(sys.stdin):
    print(f\"{ds['name']}: uid={ds['uid']}\")
"

# Ensure the metrics exist
curl -sS http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=pg_up' | python3 -c "
import sys,json
d = json.load(sys.stdin)
print(f\"pg_up series: {len(d['data'].get('result',[]))}\")
"
```

### 13.9 Can't SSH to production server with deploy_key

The key was rotated. Re-add the current public key to the server:
```bash
cat /opt/kimkom-commandcenter/ssh/deploy_key.pub
# ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOuWELPp5kpEHCTjqQhJ9HNXsGjf5QMsm6OnLdEqeM9+ kimkom-deploy

# On the target server:
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOuWELPp5kpEHCTjqQhJ9HNXsGjf5QMsm6OnLdEqeM9+ kimkom-deploy' >> ~/.ssh/authorized_keys
```

---

## 14. Credentials and Secrets Reference

| What | Where | Format | Mode |
|---|---|---|---|
| CommandCenter .env | `/opt/kimkom-commandcenter/.env` | POSTGRES_PASSWORD, GRAFANA_PASSWORD, etc. | 0600 |
| Instance .env | `instances/<client>/.env` | DB_PASSWORD, ODOO_ADMIN_PASSWORD, GLITCHTIP_DSN | 0600 |
| Instance odoo.conf | `instances/<client>/config/odoo.conf` | admin_passwd, db_password, sentry_dsn | 0640, group:lxd(101) |
| Deploy SSH key | `ssh/deploy_key` | ED25519 private key | 0600 |
| GlitchTip API token | `secrets/commandcenter/glitchtip-api-token` | Bearer token | 0600 |
| Restic password | `secrets/commandcenter/restic-password` | Encryption password | 0600 |
| Alertmanager secrets | `secrets/commandcenter/alertmanager-secrets` | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID | 0600 |
| GlitchTip .env | `glitchtip/.env` | POSTGRES_PASSWORD, SECRET_KEY | 0600 |
| GlitchTip DSNs | `glitchtip/dsns.json` | Project DSNs | 0600 |
| Rclone config | `rclone/rclone.conf` | S3 access keys | 0600 |
| Production .env | `/opt/kimkom-<slug>/.env` on PROD | All service passwords | 0600 |
| Production backup | `/etc/kimkom-backup-v2/` on PROD | Restic password, AWS credentials | 0600 (root-only) |

**All tracked credentials (in Git history before sanitization) were rotated.** Do NOT re-use old passwords:
- Old SSH deploy key: revoked
- Old PostgreSQL passwords: rotated (new: tREgb1nghkl1wphh3BdYXkQN0qFc2BuT)
- Old Odoo admin passwords: rotated
- Old GlitchTip token: replaced with least-privilege read-only token

---

## Quick Reference Card

```bash
# Dev: create instance
./scripts/create-odoo-instance.sh --client <name>

# Dev: rebuild and restart
docker compose -f instances/<name>/docker-compose.yml --env-file instances/<name>/.env build --no-cache odoo
docker compose -f instances/<name>/docker-compose.yml --env-file instances/<name>/.env up -d --force-recreate --wait --wait-timeout 300

# Dev: install/upgrade module
docker compose -f instances/<name>/docker-compose.yml --env-file instances/<name>/.env run --rm odoo -- -i|u <module> --stop-after-init --no-http

# Dev: copy sentry module
cp -r instances/SuperTCG/addons-oca/sentry instances/<name>/addons-oca/

# Modules: push to GitHub
cd /opt/kimkom-modules && git add -A && git commit -m "..." && git push origin main

# Stack: push to GitHub
cd /opt/KimKom-stack && git add -A && git commit -m "..." && git push origin main

# CC: push to GitHub
cd /opt/kimkom-commandcenter && git add -A && git commit -m "..." && git push origin HEAD:main

# Prod: provision new customer
cd /opt/KimKom-stack && ./init-client.sh --server <ip> --client <name> --domain <domain> --odoo-image <digest> --backup-s3-key <key> --backup-s3-secret <secret> --tailscale-token <key> --resume

# Prod: deploy update
cd /opt/KimKom-stack && ./update.sh --server <tailscale-ip> --client-slug <slug> --ssh-user alex --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key

# Prod: manual backup
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> 'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env /opt/kimkom-<slug>/scripts/backup-v2/backup.sh'

# Prod: verify restore
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> 'sudo env BACKUP_V2_CONFIG=/etc/kimkom-backup-v2.env /opt/kimkom-<slug>/scripts/backup-v2/verify-restore.sh'

# CC: check all endpoints
for h in kimkom-dev.kimkom.net supertcg.kimkom.net vranckeneers.kimkom.net kimkom-prod.kimkom.net; do printf '%s: %s\n' "$h" $(curl -sSL -o /dev/null -w '%{http_code}' "https://$h/web/login"); done

# CC: check Prometheus
curl -sS http://127.0.0.1:9090/api/v1/targets | python3 -c "import sys,json; t=json.load(sys.stdin)['data']['activeTargets']; u=sum(1 for x in t if x['health']=='up'); print(f'{u}/{len(t)} targets up')"

# CC: check alerts
curl -sS http://127.0.0.1:9090/api/v1/alerts | python3 -c "import sys,json; a=json.load(sys.stdin)['data']['alerts']; f=sum(1 for x in a if x['state']=='firing'); print(f'{f} alerts firing')"
```