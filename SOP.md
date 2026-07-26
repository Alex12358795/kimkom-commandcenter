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
11. [GlitchTip Ownership](#11-glitchtip-ownership)
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
    ↓ SSH (deploy_key) → update.sh → exact detached SHA/image update
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
This Phase 1 flow applies **only to new clients and new modules**. Existing
SuperTCG, Vranckeneers, and kimkom-dev instances retain their instance-local
mounts and are not migrated by this procedure.

The generator creates and configures a new development runtime only. Before
running it, maintainers must initialize or update the reviewed Git workspace
separately through the module workflow under
`/opt/kimkom-modules/<client-slug>/` and `/opt/kimkom-modules/shared/` (or the
configured `KIMKOM_MODULES_ROOT`). It never clones source. The generated Odoo
containers mount these client and shared paths read-only.

### Dev instance creation

New dev instances are created with `create-odoo-instance.sh`. It validates the
client slug, creates a dedicated PostgreSQL role/database, generates
docker-compose.yml with read-only module mounts and resource limits, and starts
Odoo. Generated defaults: workers=0, one cron thread, 0.75 CPU, 1280 MiB memory
limit, PostgreSQL CONNECTION LIMIT 10.

### 2.1 Create the instance

```bash
cd /opt/kimkom-commandcenter
./scripts/create-odoo-instance.sh --client Acme
# Optional alternate workspace root (the default is /opt/kimkom-modules):
KIMKOM_MODULES_ROOT=/opt/kimkom-modules ./scripts/create-odoo-instance.sh --client Acme
```

This creates:
- `instances/acme/` directory
- `instances/acme/docker-compose.yml` (Traefik labels, rate limiting, WebSocket)
- `instances/acme/config/odoo.conf` (dedicated DB role; optional legacy GlitchTip integration is separate)
- `instances/acme/.env` (DB_PASSWORD, ODOO_ADMIN_PASSWORD)
- `instances/acme/Dockerfile` (generator-defined dependencies; no sentry-sdk claim)
- `/opt/kimkom-modules/acme/` and `/opt/kimkom-modules/shared/` — direct host-editable module workspaces
- `instances/acme/addons-enterprise/`, `addons-oca/`, and `addons-external/` — per-instance dependency directories
- `instances/acme/data/` — filestore, chown 100:101
- Dedicated PostgreSQL role `odoo_acme` and database `odoo_acme`
- Odoo MCP config entry

The non-dry-run generator builds, initializes, and starts the Odoo container.
Do not run a second startup command as part of generation; proceed to
verification.

Prepare and review the two module workspaces separately before starting the
runtime. Existing legacy instance-local trees remain out of scope and
untouched.

### 2.2 Verify

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

### 2.5 Reserve GlitchTip project

For a clean customer, run the provisioning script as described in Section 6.5.
It owns project creation and the protected DSN reference; there is no separate
manual GlitchTip connection or DSN-copy procedure.

### 2.6 Dependency modules (if needed)

For the clean new-customer path, record each dependency as an explicit selected
module name, source, and 40-character source commit in the simple manifest.
The client/shared workspace model is direct source under
`/opt/kimkom-modules/<client-slug>/` and `/opt/kimkom-modules/shared/`; do not
copy custom modules into an instance-local `addons/` tree. The existing
SuperTCG, Vranckeneers, and kimkom-dev instance-local legacy trees are out of
scope and remain untouched.

---

## 3. Developing Odoo Modules

### 3.1 Find where the modules live

New dev instances mount source workspaces as read-only bind mounts:

| Mount | Path on host | Contents |
|---|---|---|
| `/mnt/kimkom-client` | `/opt/kimkom-modules/<client>/` | Client-specific modules |
| `/mnt/kimkom-shared` | `/opt/kimkom-modules/shared/` | Shared modules |
| `/mnt/extra-enterprise` | `instances/<client>/addons-enterprise/` | Odoo Enterprise |
| `/mnt/extra-oca` | `instances/<client>/addons-oca/` | OCA community modules |
| `/mnt/extra-external` | `instances/<client>/addons-external/` | External dependencies |

All source mounts are read-only; containers must not write to module workspaces.

### 3.2 Create a new module

```bash
cd /opt/kimkom-modules/<client>/
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

### 4.3 Edit the modules workspace directly

```bash
# Client-specific modules are edited directly in:
cd /opt/kimkom-modules/<client-slug>
# Shared modules are edited directly in:
cd /opt/kimkom-modules/shared
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

Use this simple shape in `/opt/KimKom-stack/clients/<client-slug>.yml`:

```json
{
  "schema_version": 3,
  "display_name": "Acme Corp",
  "slug": "acme",
  "profiles": ["core"],
  "target_rpo": "1h",
  "target_rto": "4h",
  "image": {"repository": "ghcr.io/alex12358795/acme-odoo", "tag": "<git-sha>"},
  "management": {"provider": "tailscale", "resource_id": "acme"},
  "network": {"provider": "tailscale", "public_address": null, "private_address": null},
  "modules": {
    "internal": {
      "repository": "alex12358795/kimkom-modules",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "client": "acme",
      "client_modules": ["acme_module"],
      "shared_modules": ["kimkom_shared_module"]
    },
    "enterprise": null,
    "sources": [{
      "name": "server-tools",
      "kind": "oca",
      "repository": "OCA/server-tools",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "modules": ["sentry"],
      "auth": "public"
    }]
  }
}
```

Every selected module list contains technical names and every source uses an
exact lowercase 40-character commit. Repositories are canonical
`owner/repository` IDs; do not use URLs, old `shared`/`client`/`oca`/`external`
keys, mutable refs, or repository-wide inclusion. `enterprise` is `null` or
an object with `repository`, `commit`, and a non-empty `modules` list. The
`<git-sha>` image tag is replaced by CI with the commit SHA; it is not a
mutable branch or release tag.

Commit and push KimKom-stack:

```bash
cd /opt/KimKom-stack
git commit -am "chore(<client>): update module manifest"
git push origin main
```

### 4.7 Verify CI

CI is required to:
1. Validate simple manifests and the per-client image matrix
2. Fetch direct workspace/dependency sources at their 40-character commits
3. Build the client image once, then fresh-install/test the selected modules
   on that same image and cold-start it
4. Emit the source-lock BOM and run the configured vulnerability gate
5. Release only from `refs/heads/main` through the protected
   `clean-client-release` environment and its required approval

Check at: `https://github.com/Alex12358795/KimKom-stack/actions`. PR jobs have no
private source or package credentials. Private external source onboarding
requires an explicitly reviewed environment-secret mapping. These are release
requirements, not evidence that private checkout, GHCR publication, Trivy,
or generated-instance runtime has been completed here.

There is no direct rsync-to-production path. Commit and push the modules repo;
release only through CI-built immutable images and the normal production
deployment process. `scripts/deploy-module.sh` is unsupported for this new
flow, as are current instance-local legacy trees.

---

## 5. Building a Production Image (CI)

The intended CI pipeline (`immutable-image.yml`) builds one image per client
in the manifest matrix. PR jobs must have no private source or package
credentials. Private external source onboarding requires an explicitly
reviewed mapping from that source to a protected environment secret.

### 5.1 How it works

1. Validate simple manifests and the client image matrix.
2. For each client, fetch sources at recorded 40-character commits, selecting
   exact module names only.
3. Build the client image once, then fresh-install/test modules on that same
   image and cold-start it.
4. Record the source-lock BOM and apply the configured vulnerability gate.
5. Permit release only from `refs/heads/main` via protected
   `clean-client-release` with required approval.

The source-lock BOM is intended to record the source commit for every selected
module. Private checkout, Trivy execution, GHCR publication, image digest, and
generated-instance runtime remain unverified until evidence is captured.

### 5.2 Manually trigger CI

1. Go to `https://github.com/Alex12358795/KimKom-stack/actions`
2. Click "Immutable image CI"
3. Click "Run workflow"
4. Select the protected release branch configured by the workflow
5. Click "Run workflow"

### 5.3 Get the image digest

After CI succeeds, get the digest:

```bash
docker pull ghcr.io/alex12358795/<slug>-odoo:<git-sha>
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/alex12358795/<slug>-odoo:<git-sha>
```

Use the `@sha256:...` value as `--odoo-image` in `init-client.sh` or in the `.env` on the production server.

---

## 6. Clean-customer manual test runbook (Phase 3 deterministic/mock; Phase 4 TEST-VM live)

This is the executable clean-customer acceptance runbook. Phase 3 is static or
mocked and must be non-mutating. Phase 4 is the only lane allowed to touch the
TEST VM or perform live backup, monitoring, Portainer, GlitchTip, or HTTPS
validation. Legacy production notes are not a dependency of this flow.

### 6.0 Required inputs and prerequisites

Before running any commands, collect these:

| Item | Required? | Where to get it |
|---|---|---|
| Customer display name | Yes | Client provides |
| Customer slug (lowercase, DNS-safe) | Yes | Set yourself (e.g., `acme`) |
| Production domain | Yes | Client provides (e.g., `acme.com`) |
| Hetzner VPS (or similar) | Yes | Fresh Ubuntu 24.04, at least 2 vCPU, 4 GB RAM, 40 GB disk |
| VPS public IP | Yes | From VPS provider console |
| VPS root password or user | Yes | From VPS provider, supplied interactively or via approved secret handling; never put it in this document |
| SSH key for VPS | Yes | Usually VPS provider adds one; we add our deploy key too |
| DNS A record | Yes | `<domain>` → VPS public IP (create before TLS phase) |
| Hetzner Object Storage bucket | Yes | Create via Hetzner Cloud Console |
| S3 access key + secret (for backups) | Yes | Create via Hetzner Cloud Console → Object Storage → Credentials |
| Tailscale auth key | **Recommended** | https://login.tailscale.com/admin/settings/keys (one-time key) |
| Odoo image digest | Yes | From CI pipeline (see Section 5.3) — `ghcr.io/alex12358795/<slug>-odoo@sha256:...` |
| GlitchTip reservation | Yes for clean customers | the provisioning script owns project creation and the private DSN reference/file |
| Module manifest | Yes | `clients/<slug>.yml` in KimKom-stack (see Section 6.1 below) |
| Modules ready in kimkom-modules repo | Yes | All customer + shared modules pushed to GitHub |
| Backup credentials | Yes | Dedicated S3 key/secret and Restic password through the approved secret input path |
| Backup escrow reference | Yes | Non-secret off-host recovery/config reference passed as `--backup-escrow-reference` |
| Private-clone deploy key | If the KimKom-stack clone is private | Distinct GitHub deploy key file passed as `--github-deploy-key-file`; do not reuse the production SSH key |
| Enterprise modules (optional) | If licensed | Exact commit SHA from Odoo's private repo |
| OCA modules (optional) | If needed | Exact commit SHAs per repo |

### 6.1 Create Module Space

```bash
# Customer-specific modules
mkdir -p /opt/kimkom-modules/<client-slug>

# If they use shared KimKom modules, ensure they're in /opt/kimkom-modules/shared/

# New modules are developed directly in /opt/kimkom-modules/<client-slug>/.
# Existing instance-local trees are legacy and are not migrated by Phase 1.

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
  "schema_version": 3,
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
    "internal": {
      "repository": "alex12358795/kimkom-modules",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "client": "acme",
      "client_modules": ["acme_module"],
      "shared_modules": ["kimkom_shared_module"]
    },
    "enterprise": null,
    "sources": [{
      "name": "server-tools",
      "kind": "oca",
      "repository": "OCA/server-tools",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "modules": ["sentry"],
      "auth": "public"
    }]
  }
}
```

**IMPORTANT:** Every selected module source must use an exact lowercase
40-character commit SHA and a canonical `owner/repository` ID. Do not use
URLs, mutable refs, or implicit repository-wide selection. Use only the
simple `internal`, `enterprise`, and `sources` keys with technical module
lists. The `<git-sha>` image tag is replaced by CI with the commit SHA.

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

### 6.5 Reserve the customer (Phase 3, non-mutating when dry-run)

the provisioning script owns GlitchTip project creation and stores only a private
DSN reference in `the instance .env`. Do not create a project, retrieve
a DSN, or copy a DSN manually. For a static check, use a temporary inventory
checkout and `--dry-run`; do not point the command at the live inventory.

```bash
tmp=$(mktemp -d)
mkdir -p "$tmp/operations" "$tmp/scripts"
cp .env.example "$tmp/the instance .env"
(cd "$tmp" &&  newco --name "Newco Test" --dry-run)
rm -rf "$tmp"
```

Expected: `ok: reserve`; no production instance, database, or live GlitchTip
project is created. The bounded fixture at
`/opt/KimKom-stack/tests/test-init-client-documentation.sh` covers the remote
state cases below without SSH or live-state writes.

### 6.6 Phase 3 static/mock checklist (non-mutating)

Use only the fixed example inventory
`/opt/kimkom-commandcenter/.env.example` or a temporary
copy of an empty `{"schema_version":1,"customers":{}}` file. Never use the
live untracked `the instance .env` for a temporary example. The ten
inventory contract checks are isolated by `tests/test_customer_ops.py` (currently
14 unittest cases) and must pass without changing inventory, secrets, or managed
targets:

```bash
python3 -m unittest -v tests/test_customer_ops.py
```

The ten expected contract outcomes are: simultaneous development/production records;
reconcile shape/idempotence; unsafe slug rejection; existing-slug name
mismatch rejection; target identity rules; missing-input rejection; Portainer
non-secret reference enforcement; rejected-input immutability; JSON-schema
invalid-record rejection; and reconcile dry-run immutability. Expected: all ten
contract outcomes pass (14 cases currently) and all writes remain in test
temporary directories.

Run the remaining deterministic checks:

```bash
python3 -m json.tool .env.example >/dev/null
./scripts/test-generate-alertmanager-config.sh
if command -v promtool >/dev/null 2>&1; then
  promtool check config monitoring/prometheus.yml
  promtool check rules monitoring/prometheus/rules/baseline.yml
else
  docker run --rm --entrypoint promtool \
    -v "/opt/kimkom-commandcenter:/work:ro" prom/prometheus:v2.53.0 \
    check config /work/monitoring/prometheus.yml
  docker run --rm --entrypoint promtool \
    -v "/opt/kimkom-commandcenter:/work:ro" prom/prometheus:v2.53.0 \
    check rules /work/monitoring/prometheus/rules/baseline.yml
fi
tmp=$(mktemp)
docker compose -f monitoring/docker-compose.yml --env-file .env config >"$tmp"
rm -f "$tmp"
python3 - <<'PY'
import json
from pathlib import Path
for path in Path("monitoring/grafana/provisioning/dashboards").glob("*.json"):
    json.loads(path.read_text())
print("dashboard JSON parse: PASS")
PY
./scripts/create-odoo-instance.sh --client acme --dry-run
./scripts/create-odoo-instance.sh --client acme --dry-run \
  -- -- "documentation fixture only"
/opt/KimKom-stack/tests/test-init-client-documentation.sh
git diff --check -- SOP.md AGENTS.md README.md
git diff --name-only -- AGENTS.md SOP.md README.md
```

Expected: the Alertmanager fixture creates and removes temporary output with
mode `0644`; promtool accepts the Prometheus config and rules; Compose renders
without starting services; dashboard JSON parses; the ordinary generator
denies this host on measured thresholds; the override dry-run renders only
temporary files; the documentation harness passes; and diff checks report no
whitespace errors; the scope listing contains only allowed documentation files.
No command starts Odoo, rewrites the live inventory, writes
secrets, or changes monitoring/runtime state.

The non-dry-run generator itself builds, initializes, and starts Odoo, so no
follow-up startup command belongs in this runbook. No clean-flow `sentry-sdk`
installation or legacy-source copy is assumed.

For the reservation-specific dry-run, copy the fixed example inventory and the

```bash
tmp=$(mktemp -d)
mkdir -p "$tmp/operations" "$tmp/scripts"
cp .env.example "$tmp/the instance .env"
(cd "$tmp" &&  newco --name "Newco Test" --dry-run)
rm -rf "$tmp"
```

Expected: `ok: reserve`; no live GlitchTip project, database, inventory, or
managed-target file is created. Prometheus target files is reserved for live
onboarding or a disposable copied checkout because it regenerates managed
target files.

Run the state fixture:

```bash
/opt/KimKom-stack/tests/test-init-client-documentation.sh
```

Expected: `init-client documentation state fixture: PASS`. It proves three
bounded documentation cases: fresh provisioning fails when a remote state file
already exists without `--resume`; `--resume` succeeds when
`EXPECTED_STACK_SHA=<same-controller-SHA>` matches; and resume fails closed for
`<different-controller-SHA>`. It does not claim that a TEST VM was provisioned.

Validate the fresh production argument contract without SSH or remote writes:

```bash
cd /opt/KimKom-stack
./init-client.sh --dry-run --server 8.8.8.8 --client "Acme Test" \
  --client-slug acme-test --domain acme.example.test \
  --odoo-image ghcr.io/example/acme-odoo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --backup-s3-key key-placeholder --backup-s3-secret secret-placeholder \
  --backup-escrow-reference vault-ref-acme-001 \
  --ssh-key /tmp/nonexistent-production-key
```

Expected: a non-secret plan is printed and no SSH, checkout, database, or live
state is touched. A private clone additionally requires
`--github-deploy-key-file /tmp/nonexistent-private-clone-key`; use that option
in this dry-run when the repository is private. The example uses a globally
routable synthetic address because the validator rejects documentation-only
RFC1918/test addresses; dry-run never connects to it.

### 6.7 Fresh provisioning command (Phase 4 TEST VM only)

Fresh means the target has no existing `.provision-state`. Do **not** include
`--resume` in this command:

```bash
cd /opt/KimKom-stack

./init-client.sh \
  --server <VPS_PUBLIC_IP> \
  --client "Acme Corp" \
  --client-slug acme \
  --domain acme.com \
  --odoo-image "ghcr.io/alex12358795/acme-odoo@sha256:abc123..." \
  --backup-s3-key "<provided-key>" \
  --backup-s3-secret "<provided-secret>" \
  --backup-escrow-reference "<off-host-reference>" \
  --github-deploy-key-file "<private-clone-key-file>" \
  --tailscale-token "<provided-token>" \
  --commandcenter-ip "100.67.52.95" \
  --ssh-user root \
  --ssh-key "<production-access-key>"
```

Use `--github-deploy-key-file` only when the private clone requires it. Do not
place any secret value in this runbook or shell history. This fresh command
requires all of: server/IP, client name and slug, domain, immutable Odoo image,
dedicated backup S3 key/secret, non-secret backup escrow reference, production
SSH access key, and—when applicable—the distinct private-clone deploy key.
Tailscale and optional profile credentials are also required when those options
are selected. Clean production onboarding runs the provisioning script and the
managed-target reconciliation as part of the onboarding contract; Portainer
remains manual until its observed endpoint reference is accepted.

If fresh provisioning fails after writing state, rerun the exact command with
`--resume` only after confirming the controller SHA matches the state file.
The fresh `--resume` failure is intentional: a state file without explicit
resume is rejected, and a resume with a mismatched SHA is rejected.

### 6.8 Portainer acceptance (Phase 4 TEST VM only)

1. Open Portainer CE at `http://100.67.52.95:9000` and add the TEST VM Docker
   Agent using its approved Tailscale endpoint. Record the endpoint ID shown by
   the UI/API; an address alone is not acceptance evidence.
2. Record the observed ID in the local inventory:
```bash
 <slug> --endpoint-ref <observed-id>
```
3. Query and verify status:
```bash
python3 - <<'PY'
import json
from pathlib import Path
c = json.loads(Path('the instance .env').read_text())['customers']['<slug>']
assert c['portainer']['status'] == 'accepted'
assert c['portainer']['endpoint_ref'] == '<observed-id>'
print('Portainer inventory status: accepted')
PY
```
Expected: accepted status matches the observed endpoint ID. A pending record is
the correct result until this manual observation occurs.

### 6.9 TEST-VM live checks and cleanup evidence

The Oracle-listed Phase 4 prerequisites are: a real encrypted Restic
repository; real Odoo/PostgreSQL dump and filestore; real pinned image; real
Docker Compose runtime; TEST VM access; and approved operator recovery access.
Run the following only on TEST:

```bash
curl -fsSIL "https://<domain>/web/login"
ssh -i "<production-access-key>" <user>@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'
ssh -i "<production-access-key>" <user>@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/verify-restore.sh'
```

Also observe Prometheus target health, generic Grafana Customer Overview
labels/backup panels, central Alertmanager grouping, GlitchTip delivery,
Portainer status, HTTPS/WebSocket/login behavior, and exact image/SHA records.
Do not claim these results from static or mock checks. There is no unsupported
manual test-alert claim; alert delivery is a live Phase 4 observation.

Cleanup evidence must include the TEST VM stack directory/state disposition,
removed temporary credentials or fixtures, disabled test timers/resources,
deleted temporary databases/filestores, and screenshots or command output
showing the final Portainer/inventory status. Preserve backup/recovery evidence
and the operator decision; do not delete required forensic artifacts.

Remaining live-only commands: all TEST VM SSH backup/restore commands above,
HTTPS/WebSocket checks, Prometheus/Grafana/Alertmanager/GlitchTip observations,
and Portainer UI/API observation. Everything in Sections 6.5–6.7 and the state
fixture is static, dry-run, temporary, or mocked.

### 6.10 Historical Phase 1/2 acceptance reference

The former production checklist is retained only as historical reference. It is
not evidence for clean Phase 3 and must not be used to create a manual DSN or
to modify legacy SuperTCG/Vranckeneers/kimkom-dev source.

<!-- historical commands intentionally omitted from the executable clean runbook -->

<!--
5. **Test backup**: SSH to server and run:
```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key <user>@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'
```
-->

---

## 7. Deploying a Production Update

There is one supported update command. It fetches and verifies exact immutable
inputs, creates one quiesced recovery point, stops Odoo (and `cron` if present),
runs the selected module upgrade, then starts and health-checks Odoo. It does
not run `git pull`, use a mutable ref, or perform a promotion step.

```bash
cd /opt/KimKom-stack
./update.sh --server <tailscale-ip> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2 --ssh-user <deployment-user> \
  --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key
```

The application environment is the deployment user's `$STACK_ROOT/.env`, not
an external `stack.env`. Restic/S3 credentials, configuration, and installed
backup tools are root-only. The implemented maintenance boundary is stopped
Odoo; no actual 503 route exists. There is no automatic rollback, cutover, or
old-release restart on failure.

## 8. Recovery after an update

After an operator decision, use the installed root-only recovery lane. Prepare
is isolated and does not change production; apply requires exact confirmation:

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key <user>@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh prepare --id <ID>'
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key <user>@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh apply --id <ID> --confirm-id <ID>'
```

Failures retain maintenance and require manual investigation; there is no
automatic data restore, image/Git rollback, promotion, or traffic cutover.

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
  'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'
```

Manual restore verification (monthly automatic):

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<tailscale-ip> \
  'sudo /usr/local/libexec/kimkom-backup-v2/verify-restore.sh'
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

Routine snapshot restore is not an automatic production operation. For an
update recovery point, use the manual `prepare` then exact-confirmed `apply`
commands in Section 8. For disaster recovery, use an approved outage plan and
TEST-VM evidence first; mock tests and isolated verification do not prove
Docker/PostgreSQL/Restic recovery.

---

## 11. GlitchTip ownership

For clean Phase 3 customers, `` owns
project creation and the private DSN reference/file. Do not create projects,
retrieve DSNs, copy DSNs from legacy instances, or add a manual sentry module
or startup step to the clean flow. Live GlitchTip delivery is a Phase 4 TEST-VM
observation only.

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

### 12.5 Reconcile Prometheus targets for a clean Phase 3 customer

Do not edit `nodes.yml`, `postgres.yml`, `http.yml`, or `https.yml` to append a
customer. Record the customer and targets in the local inventory, then let the
idempotent reconciler generate managed file-SD JSON:

```bash
 <slug> --name "Customer Name" \
  --domain <domain> --management-target <tailscale-ip>:9001 \
  --node-target <tailscale-ip>:9100 --postgres-target <tailscale-ip>:9187 \
  --http-target http://<domain> --https-target https://<domain>

```

Prometheus live health is a Phase 4 validation; the command succeeding only
proves deterministic inventory and file generation.

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

### 13.7 Legacy GlitchTip integration not receiving events

```bash
# Legacy-instance check only; clean generated clients do not assume sentry-sdk.
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
| Clean generated instance .env | `instances/<client>/.env` | DB_PASSWORD, ODOO_ADMIN_PASSWORD | 0600 |
| Instance odoo.conf | `instances/<client>/config/odoo.conf` | admin_passwd, db_password; legacy sentry_dsn only where explicitly configured | 0640, group:lxd(101) |
| Deploy SSH key | `ssh/deploy_key` | ED25519 private key | 0600 |
| GlitchTip API token | `secrets/commandcenter/glitchtip-api-token` | Bearer token | 0600 |
| Restic password | `secrets/commandcenter/restic-password` | Encryption password | 0600 |
| Alertmanager secrets | `secrets/commandcenter/alertmanager-secrets` | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID | 0600 |
| GlitchTip .env | `glitchtip/.env` | POSTGRES_PASSWORD, SECRET_KEY | 0600 |
| GlitchTip DSNs | `glitchtip/dsns.json` | Project DSNs | 0600 |
| Rclone config | `rclone/rclone.conf` | S3 access keys | 0600 |
| Production .env | `/opt/kimkom-kimkom-prod/.env` on TEST (example) | All service passwords | 0600 |
| Production backup | `/etc/kimkom-backup-v2/` on PROD | Restic password, AWS credentials | 0600 (root-only) |

**All tracked credentials (in Git history before sanitization) were rotated.** Do NOT re-use old passwords:
- Old SSH deploy key: revoked
- Old PostgreSQL passwords: rotated; retrieve current values only through approved secret storage
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

# Dev: edit new client modules directly in /opt/kimkom-modules/<name>/;
# legacy SuperTCG mounts are excluded from this new-client procedure.

# Modules: push to GitHub
cd /opt/kimkom-modules && git add -A && git commit -m "..." && git push origin main

# Stack: push to GitHub
cd /opt/KimKom-stack && git add -A && git commit -m "..." && git push origin main

# CC: push to GitHub
cd /opt/kimkom-commandcenter && git add -A && git commit -m "..." && git push origin HEAD:main

# Prod: provision new customer
cd /opt/KimKom-stack && ./init-client.sh --server <ip> --client <name> --domain <domain> --odoo-image <digest> --backup-s3-key <key> --backup-s3-secret <secret> --backup-escrow-reference <reference>

# Prod: deploy update
cd /opt/KimKom-stack && ./update.sh --server <tailscale-ip> --client-slug <slug> \
  --target-sha <40-hex-sha> --target-image <image@sha256:digest> \
  --upgrade-modules module1,module2 --ssh-user <user> --ssh-key /opt/kimkom-commandcenter/ssh/deploy_key

# Prod: manual backup
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key <user>@<tailscale-ip> 'sudo /usr/local/libexec/kimkom-backup-v2/backup.sh'

# Prod: verify restore
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key <user>@<tailscale-ip> 'sudo /usr/local/libexec/kimkom-backup-v2/verify-restore.sh'

# CC: check all endpoints
for h in kimkom-dev.kimkom.net supertcg.kimkom.net vranckeneers.kimkom.net kimkom-prod.kimkom.net; do printf '%s: %s\n' "$h" $(curl -sSL -o /dev/null -w '%{http_code}' "https://$h/web/login"); done

# CC: check Prometheus
curl -sS http://127.0.0.1:9090/api/v1/targets | python3 -c "import sys,json; t=json.load(sys.stdin)['data']['activeTargets']; u=sum(1 for x in t if x['health']=='up'); print(f'{u}/{len(t)} targets up')"

# CC: check alerts
curl -sS http://127.0.0.1:9090/api/v1/alerts | python3 -c "import sys,json; a=json.load(sys.stdin)['data']['alerts']; f=sum(1 for x in a if x['state']=='firing'); print(f'{f} alerts firing')"
```
