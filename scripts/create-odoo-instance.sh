#!/usr/bin/env bash
set -euo pipefail

show_help() {
    cat <<EOF
Usage: $0 [--client <name>] [--admin-pass <pass>] [--github <repo-url>]

Creates a new isolated Odoo 18 development instance and MCP config.
Prompts for client name interactively if not provided.

Options:
  --client      Client name (e.g., "supertcg", "acme") — becomes the subdomain
  --admin-pass  Odoo admin password (default: auto-generated)
  --github      GitHub repo URL for custom modules (optional)
  --help        Show this message

Examples:
  $0
  $0 --client acme --github https://github.com/you/acme-modules
EOF
    exit 0
}

CLIENT=""
ADMIN_PASS=""
GITHUB_REPO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --client) CLIENT="$2"; shift 2 ;;
        --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
        --github) GITHUB_REPO="$2"; shift 2 ;;
        --help) show_help ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Interactive prompt if no client name
if [ -z "$CLIENT" ]; then
    read -p "Enter client name (e.g., supertcg, acme): " CLIENT
    CLIENT="${CLIENT,,}"  # lowercase
    CLIENT="${CLIENT// /_}"  # spaces -> underscores
    if [ -z "$CLIENT" ]; then
        echo "ERROR: Client name is required"
        exit 1
    fi
fi

if [[ ! "$CLIENT" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "ERROR: Client must contain only lowercase letters, digits, underscores, and hyphens"
    exit 1
fi

if [ -d "/opt/kimkom-commandcenter/instances/$CLIENT" ]; then
    echo "ERROR: Instance $CLIENT already exists at /opt/kimkom-commandcenter/instances/$CLIENT"
    exit 1
fi

if [ -z "$ADMIN_PASS" ]; then
    ADMIN_PASS=$(openssl rand -hex 16)
fi

DB_SUFFIX="${CLIENT//-/_}"
DB_NAME="odoo_${DB_SUFFIX}"
DB_ROLE="odoo_${DB_SUFFIX}"
INSTANCE_DIR="/opt/kimkom-commandcenter/instances/$CLIENT"
DB_PASSWORD=$(openssl rand -hex 24)

echo "Creating Odoo instance: $CLIENT"
echo "  DB:   $DB_NAME"
echo "  Role: $DB_ROLE"

mkdir -p "$INSTANCE_DIR/config" "$INSTANCE_DIR/data" "$INSTANCE_DIR/addons" "$INSTANCE_DIR/addons-enterprise" "$INSTANCE_DIR/addons-oca"

# --- Dockerfile ---
cat > "$INSTANCE_DIR/Dockerfile" <<DOCKERFILE
FROM odoo:18

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

# --- .gitignore for addons/ ---
cat > "$INSTANCE_DIR/addons/.gitignore" <<GITIGNORE
/*
GITIGNORE

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
addons_path = /mnt/extra-addons,/mnt/extra-enterprise,/mnt/extra-oca,/usr/lib/python3/dist-packages/odoo/addons
data_dir = /var/lib/odoo/data
proxy_mode = True
workers = 4
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
sudo chown "$(id -u):101" "$INSTANCE_DIR/config/odoo.conf"
chmod 0640 "$INSTANCE_DIR/config/odoo.conf"

# --- docker-compose.yml (no host port mapping — Traefik routes via Docker network) ---
cat > "$INSTANCE_DIR/docker-compose.yml" <<YML
services:
  odoo:
    build: .
    container_name: odoo-$CLIENT
    restart: unless-stopped
    volumes:
      - ./config/odoo.conf:/etc/odoo/odoo.conf:ro
      - ./addons:/mnt/extra-addons
      - ./addons-enterprise:/mnt/extra-enterprise
      - ./addons-oca:/mnt/extra-oca
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

# Optionally clone custom modules from GitHub
if [ -n "$GITHUB_REPO" ]; then
    git clone "$GITHUB_REPO" "$INSTANCE_DIR/addons/$CLIENT"
    echo "Cloned $GITHUB_REPO to $INSTANCE_DIR/addons/$CLIENT"
fi

# Create a dedicated non-superuser role and database for this client.
docker exec odoo-postgres psql -U odoo -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE \"$DB_ROLE\" LOGIN PASSWORD '$DB_PASSWORD';"
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

echo ""
echo "=== Instance $CLIENT created ==="
echo "URL:       https://$CLIENT.kimkom.net"
echo "DB:        $DB_NAME"
echo "Admin credentials are stored in $INSTANCE_DIR/.env and the MCP configuration."
echo ""
echo "Next: add catch-all route in Cloudflare Tunnel:"
echo "  $CLIENT.kimkom.net → http://192.168.178.19:80"
