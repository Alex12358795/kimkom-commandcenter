#!/usr/bin/env bash
set -euo pipefail

S3_CONFIG="/opt/kimkom-commandcenter/rclone/rclone.conf"
REGISTRY="/opt/kimkom-commandcenter/rclone/clients.json"

echo "=== Backup Status ==="

if [ ! -f "$REGISTRY" ] || [ ! -f "$S3_CONFIG" ]; then
    echo "No S3 remotes configured. Run ./scripts/add-s3-remote.sh"
    exit 1
fi

echo "Registered S3 remotes:"
python3 -c "
import json
reg = json.load(open('$REGISTRY'))
for c, v in reg.items():
    bp = v.get('backup_prefix', '')
    print(f'  {c} → {v[\"bucket\"]}/{bp}')
"

echo ""
echo "=== S3 Backup List ==="
for CLIENT in $(python3 -c "import json; print('\n'.join(json.load(open('$REGISTRY')).keys()))"); do
    REMOTE=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT']['remote'])")
    BUCKET=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT']['bucket'])")
    BP=$(python3 -c "import json; print(json.load(open('$REGISTRY'))['$CLIENT'].get('backup_prefix', ''))")
    echo "--- $CLIENT ($BUCKET/$BP) ---"
    rclone ls "$REMOTE:$BP" --config "$S3_CONFIG" --max-depth 1 2>/dev/null | awk '{print "  " $2 " (" $1 " bytes)"}' || echo "  (error or empty)"
done

echo ""
echo "=== Local Odoo Instances ==="
for d in /opt/kimkom-commandcenter/instances/*/; do
    name=$(basename "$d")
    db_exists=$(docker exec odoo-postgres psql -U odoo -lqt 2>/dev/null | grep -c "odoo$name" || true)
    running=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c "odoo-$name" || true)
    db_flag="DB: $([ "$db_exists" -gt 0 ] && echo 'exists' || echo 'missing')"
    ctn_flag="Container: $([ "$running" -gt 0 ] && echo 'running' || echo 'stopped')"
    echo "  $name → $db_flag, $ctn_flag"
done
