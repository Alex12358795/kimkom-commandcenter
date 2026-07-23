#!/usr/bin/env bash
set -euo pipefail

S3_CONFIG="/opt/kimkom-commandcenter/rclone/rclone.conf"
REGISTRY="/opt/kimkom-commandcenter/rclone/clients.json"
TMPDIR="/tmp/odoo-restore-$$"

cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

if [ ! -f "$S3_CONFIG" ] || [ ! -f "$REGISTRY" ]; then
    echo "Missing rclone config or registry. Run ./scripts/add-s3-remote.sh first."
    exit 1
fi

echo "=== Step 1: Which client's S3? ==="
CLIENTS=($(python3 -c "import json; print('\n'.join(json.load(open('$REGISTRY')).keys()))"))

if [ ${#CLIENTS[@]} -eq 0 ]; then
    echo "No clients registered. Run ./scripts/add-s3-remote.sh first."
    exit 1
fi

select CLIENT in "${CLIENTS[@]}"; do
    if [ -n "$CLIENT" ]; then break; fi
    echo "Invalid choice"
done

REMOTE=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT']['remote'])")
BUCKET=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT']['bucket'])")
BACKUP_PREFIX=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT'].get('backup_prefix', ''))")

REMOTE_PATH="$REMOTE:$BACKUP_PREFIX"

echo ""
echo "Fetching backups from $REMOTE_PATH..."

FILES=$(mktemp)
rclone ls "$REMOTE_PATH" --config "$S3_CONFIG" --max-depth 1 | awk '{print $2}' > "$FILES"

if [ ! -s "$FILES" ]; then
    echo "No backup files found in $REMOTE_PATH"
    rm "$FILES"
    exit 0
fi

# Display with sizes
nl -w3 -s': ' "$FILES" | while read -r line; do
    fname=$(echo "$line" | cut -d' ' -f2-)
    size=$(rclone size "$REMOTE_PATH$fname" --config "$S3_CONFIG" --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d['bytes']/1024/1024:.1f}MB')" 2>/dev/null || echo "?")
    echo "  $fname  ($size)"
done

echo ""
files_arr=()
while IFS= read -r f; do files_arr+=("$f"); done < "$FILES"
rm "$FILES"

select BACKUP_FILE in "${files_arr[@]}"; do
    if [ -n "$BACKUP_FILE" ]; then break; fi
    echo "Invalid choice"
done

echo ""
echo "=== Step 2: Restore to which local instance? ==="
INSTANCES=()
for d in /opt/kimkom-commandcenter/instances/*/; do
    name=$(basename "$d")
    if [ -f "$d/docker-compose.yml" ]; then
        INSTANCES+=("$name")
    fi
done

if [ ${#INSTANCES[@]} -eq 0 ]; then
    echo "No Odoo instances found in /opt/kimkom-commandcenter/instances/"
    exit 1
fi

select TARGET in "${INSTANCES[@]}"; do
    if [ -n "$TARGET" ]; then break; fi
    echo "Invalid choice"
done

echo ""
echo "Downloading $BACKUP_FILE..."
mkdir -p "$TMPDIR"
rclone copy "$REMOTE_PATH$BACKUP_FILE" "$TMPDIR/" --config "$S3_CONFIG" --progress

FULL_PATH="$TMPDIR/$BACKUP_FILE"
DB_NAME="odooclient${TARGET##client}"
INSTANCE_DATA="/opt/kimkom-commandcenter/instances/$TARGET/data"

echo "Detecting backup format from: $BACKUP_FILE"

case "$BACKUP_FILE" in
    *.tar.gz|*.tgz)
        echo "Format: tar.gz archive"
        mkdir -p "$TMPDIR/extracted"
        tar xzf "$FULL_PATH" -C "$TMPDIR/extracted"
        echo "Archive contents:"
        find "$TMPDIR/extracted" -maxdepth 2 -ls 2>/dev/null | head -30

        DUMP_FILE=$(find "$TMPDIR/extracted" -name "*.dump" -o -name "*.sql" -o -name "*.sql.gz" | head -1)
        FILESTORE_DIR=$(find "$TMPDIR/extracted" -type d -name "filestore" | head -1)

        if [ -n "$DUMP_FILE" ]; then
            echo "Found database dump: $DUMP_FILE"
            docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
            docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
            case "$DUMP_FILE" in
                *.gz) zcat "$DUMP_FILE" | docker exec -i odoo-postgres pg_restore -U odoo -d "$DB_NAME" ;;  
                *)    docker exec -i odoo-postgres pg_restore -U odoo -d "$DB_NAME" < "$DUMP_FILE" ;;
            esac
            echo "Database restored"
        else
            echo "No recognized dump file found inside archive."
            echo "Files found:"
            find "$TMPDIR/extracted" -type f | head -20
            exit 1
        fi

        if [ -n "$FILESTORE_DIR" ]; then
            mkdir -p "$INSTANCE_DATA"
            cp -a "$FILESTORE_DIR" "$INSTANCE_DATA/"
            sudo chown -R 101:101 "$INSTANCE_DATA"
            echo "Filestore restored"
        fi
        ;;
    *.zip)
        echo "Format: Odoo zip backup (DB + filestore)"
        unzip -q "$FULL_PATH" -d "$TMPDIR/extracted"
        DUMP_FILE=$(find "$TMPDIR/extracted" -name "*.dump" | head -1)
        FILESTORE_DIR=$(find "$TMPDIR/extracted" -type d -name "filestore" | head -1)

        if [ -z "$DUMP_FILE" ]; then
            echo "No .dump file found in zip"; exit 1
        fi
        docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
        docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
        docker exec -i odoo-postgres pg_restore -U odoo -d "$DB_NAME" < "$DUMP_FILE"

        if [ -n "$FILESTORE_DIR" ]; then
            mkdir -p "$INSTANCE_DATA/filestore"
            cp -a "$FILESTORE_DIR"/* "$INSTANCE_DATA/filestore/"
            sudo chown -R 101:101 "$INSTANCE_DATA/filestore"
            echo "Filestore restored"
        fi
        ;;
    *.dump)
        echo "Format: pg_dump (custom format)"
        docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
        docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
        docker exec -i odoo-postgres pg_restore -U odoo -d "$DB_NAME" < "$FULL_PATH"
        ;;
    *.sql.gz)
        echo "Format: gzipped SQL"
        docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
        docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
        zcat "$FULL_PATH" | docker exec -i odoo-postgres psql -U odoo -d "$DB_NAME"
        ;;
    *.sql)
        echo "Format: plain SQL"
        docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
        docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
        docker exec -i odoo-postgres psql -U odoo -d "$DB_NAME" < "$FULL_PATH"
        ;;
    *)
        echo "Unknown format. Attempting pg_restore..."
        docker exec -i odoo-postgres psql -U odoo -c "DROP DATABASE IF EXISTS $DB_NAME;"
        docker exec -i odoo-postgres psql -U odoo -c "CREATE DATABASE $DB_NAME OWNER odoo;"
        docker exec -i odoo-postgres pg_restore -U odoo -d "$DB_NAME" < "$FULL_PATH" 2>/dev/null || {
            echo "ERROR: Could not restore. Format not recognized."
            exit 1
        }
        ;;
esac

echo "Restarting Odoo container for $TARGET..."
docker restart "odoo-$TARGET"

PORT=$(docker port "odoo-$TARGET" 8069 2>/dev/null | head -1 | sed 's/.*://' || echo "$TARGET port unknown")
echo ""
echo "=== Restore Complete ==="
echo "Client: $CLIENT"
echo "Target: $TARGET"
echo "DB:     $DB_NAME"
echo "Local:  http://localhost:$PORT"
echo "Web:    https://$TARGET.kimkom.net"
echo ""
echo "Admin password is in /opt/kimkom-commandcenter/instances/$TARGET/.env"
