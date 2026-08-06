#!/usr/bin/env bash
set -euo pipefail

show_help() {
    cat <<EOF
Usage: $0 [--client <name>] [--admin-pass <pass>] [--odoo-version <18|19>] [--dry-run]

Creates a new isolated Odoo development instance and MCP config.
Prompts for client name interactively if not provided.

Options:
  --client        New client name (e.g., "acme") — becomes the subdomain
  --admin-pass    Odoo admin password (default: auto-generated)
  --odoo-version  Odoo major version for the instance image (18 or 19; default: 18)
  --dry-run       Render and validate files without creating a customer, database, MCP entry, or Docker resources
  --help          Show this message

Examples:
  $0
  $0 --client acme
  $0 --client acme --odoo-version 19
EOF
    exit 0
}

# Source workspaces must be prepared separately through the reviewed module
# workflow.  Refuse the removed cloning option before doing any other work.
for arg in "$@"; do
    if [ "$arg" = "--github" ]; then
        echo 'ERROR: --github was removed; prepare the reviewed workspace under $KIMKOM_MODULES_ROOT/<slug> before generating an instance.' >&2
        exit 2
    fi
done

CLIENT=""
ADMIN_PASS=""
ODOO_VERSION="18"
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --client)
            [ "$#" -ge 2 ] || { echo "ERROR: --client requires a value" >&2; exit 1; }
            CLIENT="$2"; shift 2 ;;
        --admin-pass)
            [ "$#" -ge 2 ] || { echo "ERROR: --admin-pass requires a value" >&2; exit 1; }
            ADMIN_PASS="$2"; shift 2 ;;
        --odoo-version)
            [ "$#" -ge 2 ] || { echo "ERROR: --odoo-version requires a value" >&2; exit 1; }
            ODOO_VERSION="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help) show_help ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate the client before any host or instance mutation.
if [ -z "$CLIENT" ]; then
    read -p "Enter new client name (e.g., acme): " CLIENT
fi
CLIENT="${CLIENT,,}"
CLIENT="${CLIENT// /-}"
if [ "$CLIENT" = "supertcg" ]; then
    echo "ERROR: supertcg is a deferred legacy instance and is unavailable for the clean new-client flow" >&2
    exit 1
fi
if [[ ! "$CLIENT" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    echo "ERROR: Client must be a lowercase slug containing letters, digits, and hyphens" >&2
    exit 1
fi

# Validate the Odoo version before any host or instance mutation.
if [ "$ODOO_VERSION" != "18" ] && [ "$ODOO_VERSION" != "19" ]; then
    echo "ERROR: invalid --odoo-version '$ODOO_VERSION' — must be 18 or 19" >&2
    exit 1
fi

if [ -d "/opt/odoo-dev/$CLIENT" ]; then
    echo "ERROR: Instance $CLIENT already exists at /opt/odoo-dev/$CLIENT"
    exit 1
fi

if [ -z "$ADMIN_PASS" ]; then
    ADMIN_PASS=$(openssl rand -hex 16)
fi

DB_SUFFIX="${CLIENT//-/_}"
DB_NAME="odoo_${DB_SUFFIX}"
DB_ROLE="odoo_${DB_SUFFIX}"
KIMKOM_MODULES_ROOT="${KIMKOM_MODULES_ROOT:-/opt/odoo-modules}"
if [[ "$KIMKOM_MODULES_ROOT" != /* || "$KIMKOM_MODULES_ROOT" == *$'\n'* || "$KIMKOM_MODULES_ROOT" == *$'\r'* || "$KIMKOM_MODULES_ROOT" == */.. || "$KIMKOM_MODULES_ROOT" == */../* || "$KIMKOM_MODULES_ROOT" == *'//' || "$KIMKOM_MODULES_ROOT" == *:* ]]; then
    echo "ERROR: KIMKOM_MODULES_ROOT must be a safe absolute path" >&2
    exit 1
fi
INSTANCE_DIR="/opt/odoo-dev/$CLIENT"
DB_PASSWORD=$(openssl rand -hex 24)

if [ ! -d "$KIMKOM_MODULES_ROOT" ] || [ -L "$KIMKOM_MODULES_ROOT" ]; then
    echo "ERROR: KIMKOM_MODULES_ROOT must be an existing, non-symlink Git worktree" >&2
    exit 1
fi
MODULES_TOP=$(git -C "$KIMKOM_MODULES_ROOT" rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$MODULES_TOP" ] || [ "$(realpath -e "$MODULES_TOP")" != "$(realpath -e "$KIMKOM_MODULES_ROOT")" ] || [ "$(git -C "$KIMKOM_MODULES_ROOT" rev-parse --is-inside-work-tree 2>/dev/null)" != true ]; then
    echo "ERROR: KIMKOM_MODULES_ROOT must be the top-level kimkom-modules Git worktree" >&2
    exit 1
fi
MODULES_ORIGIN=$(git -C "$KIMKOM_MODULES_ROOT" config --get remote.origin.url || true)
case "$MODULES_ORIGIN" in
    git@github.com:Alex12358795/kimkom-modules.git|git@github.com:Alex12358795/kimkom-modules|https://github.com/Alex12358795/kimkom-modules.git|https://github.com/Alex12358795/kimkom-modules|ssh://git@github.com/Alex12358795/kimkom-modules.git|ssh://git@github.com/Alex12358795/kimkom-modules)
        ;;
    *)
        echo "ERROR: kimkom-modules origin is not an accepted Alex12358795 canonical remote" >&2
        exit 1
        ;;
esac

echo "Creating Odoo instance: $CLIENT"
echo "  Odoo: $ODOO_VERSION"
echo "  DB:   $DB_NAME"
echo "  Role: $DB_ROLE"

if [ "$DRY_RUN" -eq 1 ]; then
    INSTANCE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/kimkom-instance-${CLIENT}.XXXXXX")
    trap 'rm -rf "$INSTANCE_DIR"' EXIT
else
    for module_dir in "$KIMKOM_MODULES_ROOT" "$KIMKOM_MODULES_ROOT/shared" "$KIMKOM_MODULES_ROOT/$CLIENT"; do
        if [ -L "$module_dir" ]; then
            echo "ERROR: Refusing symlinked module directory: $module_dir" >&2
            exit 1
        fi
    done
    mkdir -p "$KIMKOM_MODULES_ROOT/shared" "$KIMKOM_MODULES_ROOT/$CLIENT"
fi
mkdir -p "$INSTANCE_DIR/config" "$INSTANCE_DIR/data" "$INSTANCE_DIR/addons-enterprise" "$INSTANCE_DIR/addons-oca" "$INSTANCE_DIR/addons-external"

# --- Dockerfile ---
cat > "$INSTANCE_DIR/Dockerfile" <<DOCKERFILE
FROM odoo:${ODOO_VERSION}

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    fsspec>=2025.3.0 \
    fsspec[s3] \
    python_slugify \
    ebaysdk \
    google-auth \
    packaging

USER odoo
DOCKERFILE

# --- odoo.conf ---
cat > "$INSTANCE_DIR/config/odoo.conf" <<ODOOCONF
[options]
admin_passwd = $ADMIN_PASS
db_host = odoo-postgres
db_port = 5432
db_user = $DB_ROLE
db_password = $DB_PASSWORD
db_name = $DB_NAME
dbfilter = ^$DB_NAME\$
list_db = False
addons_path = /mnt/kimkom-client,/mnt/kimkom-shared,/mnt/extra-enterprise,/mnt/extra-oca,/mnt/extra-external,/usr/lib/python3/dist-packages/odoo/addons
data_dir = /var/lib/odoo/data
proxy_mode = True
workers = 0
limit_memory_soft = 536870912
limit_memory_hard = 1073741824
limit_time_cpu = 60
limit_time_real = 120
max_cron_threads = 1
log_level = info
ODOOCONF

# --- .env ---
cat > "$INSTANCE_DIR/.env" <<ENVFILE
DB_PASSWORD=$DB_PASSWORD
ODOO_ADMIN_PASSWORD=$ADMIN_PASS
ENVFILE
chmod 0600 "$INSTANCE_DIR/.env"
if [ "$DRY_RUN" -eq 0 ]; then
    sudo chown "$(id -u):101" "$INSTANCE_DIR/config/odoo.conf"
fi
chmod 0640 "$INSTANCE_DIR/config/odoo.conf"

# --- docker-compose.yml (no host port mapping — Traefik routes via Docker network) ---
cat > "$INSTANCE_DIR/docker-compose.yml" <<YML
services:
  odoo:
    build: .
    container_name: odoo-$CLIENT
    restart: unless-stopped
    cpus: "0.75"
    mem_limit: 1280m
    mem_reservation: 768m
    pids_limit: 256
    volumes:
      - ./config/odoo.conf:/etc/odoo/odoo.conf:ro
      - $KIMKOM_MODULES_ROOT/$CLIENT:/mnt/kimkom-client:ro
      - $KIMKOM_MODULES_ROOT/shared:/mnt/kimkom-shared:ro
      - ./addons-enterprise:/mnt/extra-enterprise:ro
      - ./addons-oca:/mnt/extra-oca:ro
      - ./addons-external:/mnt/extra-external:ro
      - ./data:/var/lib/odoo/data
    environment:
      DB_HOST: odoo-postgres
      DB_PORT: 5432
      DB_USER: $DB_ROLE
      DB_PASSWORD: \${DB_PASSWORD}
      DB_NAME: $DB_NAME
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8069/web/health', timeout=5).read()"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    labels:
      - com.kimkom.client=$CLIENT
      - com.kimkom.environment=development
      - com.kimkom.managed=true
      - traefik.enable=true
      - traefik.http.routers.$CLIENT.rule=Host(\`$CLIENT.kimkom.net\`)
      - traefik.http.routers.$CLIENT.entrypoints=http
      - traefik.http.routers.$CLIENT.service=$CLIENT
      - traefik.http.services.$CLIENT.loadbalancer.server.port=8069
    networks:
      - odoo-proxy

networks:
  odoo-proxy:
    name: odoo-proxy
    external: true
YML

if [ "$DRY_RUN" -eq 1 ]; then
    if command -v docker >/dev/null 2>&1; then
        docker compose -f "$INSTANCE_DIR/docker-compose.yml" config >/dev/null
    fi
    echo "Dry run passed. Generated compose/config in temporary directory: $INSTANCE_DIR"
    exit 0
fi

# Create a dedicated non-superuser role and database for this client.
docker exec odoo-postgres psql -U odoo -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE \"$DB_ROLE\" LOGIN NOSUPERUSER CONNECTION LIMIT 10 PASSWORD '$DB_PASSWORD';"
if ! docker exec odoo-postgres createdb -U odoo -O "$DB_ROLE" "$DB_NAME"; then
    docker exec odoo-postgres psql -U odoo -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP ROLE \"$DB_ROLE\";"
    exit 1
fi

# Register in MCP config
MCP_CONFIG="/opt/odoo-mcp/odoo_config.json"
if [ -f "$MCP_CONFIG" ]; then
    cp "$MCP_CONFIG" "${MCP_CONFIG}.bak"
    python3 -c "
import json
with open('$MCP_CONFIG') as f:
    cfg = json.load(f)
cfg['instances']['$CLIENT'] = {
    'url': 'http://odoo-$CLIENT:8069',
    'db': '$DB_NAME',
    'username': 'admin',
    'password': '$ADMIN_PASS',
    'transport': 'xmlrpc'
}
with open('$MCP_CONFIG', 'w') as f:
    json.dump(cfg, f, indent=2)
"
    echo "Updated MCP config with $CLIENT instance"
fi

# Build and initialize before starting the long-running service.
echo "Building custom Odoo image..."
docker compose -f "$INSTANCE_DIR/docker-compose.yml" --env-file "$INSTANCE_DIR/.env" build

sudo chown -R 100:101 "$INSTANCE_DIR/data"
docker compose -f "$INSTANCE_DIR/docker-compose.yml" --env-file "$INSTANCE_DIR/.env" \
    run --rm odoo -d "$DB_NAME" -i base --without-demo=all --stop-after-init --no-http
docker compose -f "$INSTANCE_DIR/docker-compose.yml" --env-file "$INSTANCE_DIR/.env" \
    run --rm -T -e ODOO_ADMIN_PASSWORD="$ADMIN_PASS" odoo odoo shell -d "$DB_NAME" --no-http <<'PY'
import os

env.ref("base.user_admin").write({"password": os.environ["ODOO_ADMIN_PASSWORD"]})
env.cr.commit()
PY

echo "Starting Odoo container..."
docker compose -f "$INSTANCE_DIR/docker-compose.yml" --env-file "$INSTANCE_DIR/.env" up -d

# Record instance metadata (no credentials)
python3 - "$INSTANCE_DIR/instance-metadata.json" "$CLIENT" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, client = sys.argv[1:]
metadata = {
    "client": client,
    "environment": "development",
    "created_at": datetime.now(timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(metadata, handle, indent=2)
    handle.write("\n")
PY
chmod 0640 "$INSTANCE_DIR/instance-metadata.json"

echo ""
echo "=== Instance $CLIENT created ==="
echo "URL:       https://$CLIENT.kimkom.net"
echo "DB:        $DB_NAME"
echo "Admin credentials are stored in $INSTANCE_DIR/.env and the MCP configuration."
echo ""
echo "Next: add catch-all route in Cloudflare Tunnel:"
echo "  $CLIENT.kimkom.net → http://192.168.178.19:80"
