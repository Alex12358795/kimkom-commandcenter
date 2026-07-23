#!/usr/bin/env bash
set -euo pipefail

# CommandCenter backup: PostgreSQL dump + filestores + configs + monitoring data
# Usage: ./scripts/backup-commandcenter.sh [--check|--verify-restore]
# Requires: docker, pg_dump, restic, rclone (optional S3)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${CC_ROOT}/backup-staging"
RESTIC_REPO="${RESTIC_REPOSITORY:-local:${CC_ROOT}/backup-repo}"
RESTIC_PW_FILE="${CC_ROOT}/secrets/commandcenter/restic-password"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=6

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

if ! command -v restic >/dev/null 2>&1; then
    log "ERROR: restic is not installed. Install with: apt install restic"
    exit 1
fi

# Ensure Restic password exists
if [ ! -f "$RESTIC_PW_FILE" ]; then
    mkdir -p "$(dirname "$RESTIC_PW_FILE")"
    openssl rand -base64 32 > "$RESTIC_PW_FILE"
    chmod 600 "$RESTIC_PW_FILE"
    log "Generated new Restic password at $RESTIC_PW_FILE"
fi
RESTIC_PASSWORD=$(cat "$RESTIC_PW_FILE")

mkdir -p "$BACKUP_DIR"
restic init --repo "$RESTIC_REPO" --password-file "$RESTIC_PW_FILE" 2>/dev/null || true

log "Starting CommandCenter backup"

# 1. PostgreSQL dump (all dev databases + odoomaster)
log "Dumping PostgreSQL databases..."
PG_DUMPS="$BACKUP_DIR/pg-dumps"
mkdir -p "$PG_DUMPS"

source "$CC_ROOT/.env"
ALL_DBS=$(docker exec odoo-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
    "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;" 2>/dev/null)

for db in $ALL_DBS; do
    log "  Dumping $db..."
    docker exec odoo-postgres pg_dump -U "$POSTGRES_USER" -Fc "$db" 2>/dev/null \
        > "$PG_DUMPS/${db}.dump" || log "  WARNING: Failed to dump $db"
done

# 2. Odoo filestores
log "Copying Odoo filestores..."
FILESTORE_DIR="$BACKUP_DIR/filestores"
mkdir -p "$FILESTORE_DIR"
for d in "$CC_ROOT"/instances/*/; do
    name=$(basename "$d")
    if [ -d "$d/data" ] && [ -n "$(ls -A "$d/data" 2>/dev/null)" ]; then
        log "  Copying $name filestore..."
        mkdir -p "$FILESTORE_DIR/$name"
        sudo cp -a "$d/data/." "$FILESTORE_DIR/$name/" 2>/dev/null || log "  WARNING: Failed to copy $name filestore"
        sudo chown -R "$(id -u):$(id -g)" "$FILESTORE_DIR/$name" 2>/dev/null || true
    fi
done

# 3. Configuration and secrets
log "Copying configuration..."
CONFIG_DIR="$BACKUP_DIR/config"
mkdir -p "$CONFIG_DIR"
cp -a "$CC_ROOT/.env" "$CONFIG_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/secrets" "$CONFIG_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/ssh" "$CONFIG_DIR/" 2>/dev/null || true
for d in "$CC_ROOT"/instances/*/; do
    name=$(basename "$d")
    mkdir -p "$CONFIG_DIR/instances/$name"
    cp -a "$d/.env" "$CONFIG_DIR/instances/$name/" 2>/dev/null || true
    cp -a "$d/config" "$CONFIG_DIR/instances/$name/" 2>/dev/null || true
    cp -a "$d/docker-compose.yml" "$CONFIG_DIR/instances/$name/" 2>/dev/null || true
done

# 4. Monitoring configs (not data - too large)
log "Copying monitoring configs..."
MONITORING_DIR="$BACKUP_DIR/monitoring"
mkdir -p "$MONITORING_DIR"
cp -a "$CC_ROOT/monitoring/prometheus.yml" "$MONITORING_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/monitoring/prometheus" "$MONITORING_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/monitoring/alertmanager" "$MONITORING_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/monitoring/blackbox" "$MONITORING_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/monitoring/grafana/provisioning" "$MONITORING_DIR/grafana-provisioning" 2>/dev/null || true
cp -a "$CC_ROOT/monitoring/docker-compose.yml" "$MONITORING_DIR/" 2>/dev/null || true

# 5. GlitchTip config
log "Copying GlitchTip config..."
GLITCHTIP_DIR="$BACKUP_DIR/glitchtip"
mkdir -p "$GLITCHTIP_DIR"
cp -a "$CC_ROOT/glitchtip/.env" "$GLITCHTIP_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/glitchtip/dsns.json" "$GLITCHTIP_DIR/" 2>/dev/null || true
cp -a "$CC_ROOT/glitchtip/docker-compose.yml" "$GLITCHTIP_DIR/" 2>/dev/null || true

# GlitchTip PostgreSQL dump
if docker ps --format '{{.Names}}' | grep -q 'glitchtip-postgres'; then
    log "  Dumping GlitchTip database..."
    GT_PG=$(docker ps --format '{{.Names}}' | grep 'glitchtip-postgres' | head -1)
    docker exec "$GT_PG" pg_dump -U glitchtip -Fc glitchtip 2>/dev/null \
        > "$GLITCHTIP_DIR/glitchtip.dump" || log "  WARNING: Failed to dump GlitchTip DB"
fi

# 6. Traefik dynamic config
log "Copying Traefik config..."
TRAEFIK_DIR="$BACKUP_DIR/traefik"
mkdir -p "$TRAEFIK_DIR"
cp -a "$CC_ROOT/volumes/traefik/dynamic" "$TRAEFIK_DIR/" 2>/dev/null || true

# 7. Write backup manifest
log "Writing backup manifest..."
cat > "$BACKUP_DIR/manifest.json" << EOF
{
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "hostname": "$(hostname)",
    "databases": [$(echo "$ALL_DBS" | sed 's/^/"/;s/$/",/' | tr -d '\n' | sed 's/,$//')],
    "instances": [$(ls -d "$CC_ROOT"/instances/*/ 2>/dev/null | xargs -I{} basename {} | sed 's/^/"/;s/$/",/' | tr -d '\n' | sed 's/,$//')],
    "restic_repo": "$RESTIC_REPO"
}
EOF

# 8. Upload to Restic repository
log "Uploading to Restic repository..."
    restic backup "$BACKUP_DIR" \
    --repo "$RESTIC_REPO" \
    --password-file "$RESTIC_PW_FILE" \
    --tag commandcenter \
    --tag "$(date -u +%Y-%m-%d)" \
    2>&1 || { log "ERROR: Restic backup failed"; exit 1; }

# 9. Apply retention
log "Applying retention policy..."
restic forget \
    --repo "$RESTIC_REPO" \
    --password-file "$RESTIC_PW_FILE" \
    --keep-daily "$RETENTION_DAILY" \
    --keep-weekly "$RETENTION_WEEKLY" \
    --keep-monthly "$RETENTION_MONTHLY" \
    --prune 2>&1 || log "WARNING: Retention failed"

# 10. Cleanup staging
rm -rf "$BACKUP_DIR"

log "Backup completed successfully"

# 11. Print stats
restic stats --repo "$RESTIC_REPO" --password-file "$RESTIC_PW_FILE" 2>/dev/null | tail -5