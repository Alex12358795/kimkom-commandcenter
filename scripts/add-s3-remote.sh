#!/usr/bin/env bash
set -euo pipefail

S3_CONFIG="/opt/kimkom-commandcenter/rclone/rclone.conf"
REGISTRY="/opt/kimkom-commandcenter/rclone/clients.json"

echo "=== Add S3 Remote ==="
read -r -p "Client name (e.g., supertcg): " CLIENT
if [ -z "$CLIENT" ]; then echo "Aborted"; exit 0; fi

if rclone listremotes --config "$S3_CONFIG" 2>/dev/null | grep -q "^${CLIENT}:"; then
    echo "ERROR: Remote '$CLIENT' already exists in rclone.conf"
    exit 1
fi

read -r -p "Hetzner S3 endpoint URL (e.g., https://fsn1.your-objectstorage.com): " ENDPOINT
read -r -p "Region (e.g., fsn1): " REGION
read -r -p "Access key ID: " ACCESS_KEY
read -r -s -p "Secret access key: " SECRET_KEY
echo ""
read -r -p "Bucket name (e.g., supertcg-prod): " BUCKET

if [ -z "$ENDPOINT" ] || [ -z "$REGION" ] || [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ] || [ -z "$BUCKET" ]; then
    echo "ERROR: All fields required"; exit 1
fi

echo ""
echo "Configuring rclone remote '$CLIENT'..."
cat >> "$S3_CONFIG" <<EOF

[$CLIENT]
type = s3
provider = Other
access_key_id = $ACCESS_KEY
secret_access_key = $SECRET_KEY
endpoint = $ENDPOINT
region = $REGION
EOF
chmod 600 "$S3_CONFIG"

echo "Testing connection..."
if rclone ls "$CLIENT:" --config "$S3_CONFIG" --max-depth 0 > /dev/null 2>&1; then
    echo "SUCCESS: Connection to '$BUCKET' works."
else
    echo "WARNING: Connection failed. Check credentials and endpoint."
    echo "Keeping config anyway — fix and retry."
fi

python3 -c "
import json
with open('$REGISTRY') as f:
    reg = json.load(f)
reg['$CLIENT'] = {'remote': '$CLIENT', 'bucket': '$BUCKET', 'endpoint': '$ENDPOINT', 'region': '$REGION'}
with open('$REGISTRY', 'w') as f:
    json.dump(reg, f, indent=2)
"

echo "Registered $CLIENT → $BUCKET"
echo "Done. Run ./scripts/backup-status.sh to verify."
