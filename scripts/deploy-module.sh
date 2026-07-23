#!/usr/bin/env bash
set -euo pipefail

show_help() {
    cat <<EOF
Usage: $0 --client <name> --server <IP|ssh-host> [--module <module-name>]

Deploys custom modules from DEV instance to PROD server via git.

Options:
  --client   Client name (matches DEV instance name)
  --server   PROD server SSH host
  --module   Specific module to deploy (optional, all modules if omitted)
  --ssh-user SSH user (default: root)
  --ssh-key  SSH key path (default: ~/.ssh/id_rsa)
  --help     Show this message

Examples:
  $0 --client acme --server 123.123.123.123
  $0 --client acme --server 123.123.123.123 --module my_custom_module
EOF
    exit 0
}

[ $# -eq 0 ] && show_help

CLIENT=""
SERVER=""
MODULE=""
SSH_USER="root"
SSH_KEY="$HOME/.ssh/id_rsa"

while [ $# -gt 0 ]; do
    case "$1" in
        --client) CLIENT="$2"; shift 2 ;;
        --server) SERVER="$2"; shift 2 ;;
        --module) MODULE="$2"; shift 2 ;;
        --ssh-user) SSH_USER="$2"; shift 2 ;;
        --ssh-key) SSH_KEY="$2"; shift 2 ;;
        --help) show_help ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

if [ -z "$CLIENT" ] || [ -z "$SERVER" ]; then
    echo "ERROR: --client and --server required"
    exit 1
fi

DEV_ADDONS="/opt/kimkom-commandcenter/instances/$CLIENT/addons"
PROD_DIR="/opt/odoo-prod/$CLIENT"

echo "=== Deploying modules for $CLIENT → $SERVER ==="

if [ ! -d "$DEV_ADDONS" ]; then
    echo "No addons directory for $CLIENT at $DEV_ADDONS"
    exit 1
fi

echo "1. Pushing modules to PROD..."
rsync -avz --delete -e "ssh -i $SSH_KEY" \
    "$DEV_ADDONS/" "$SSH_USER@$SERVER:$PROD_DIR/addons/"

if [ -n "$MODULE" ]; then
    echo "2. Upgrading module $MODULE on PROD..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER" "docker exec odoo-prod odoo -d $CLIENT -u $MODULE --stop-after-init --no-http"
else
    echo "2. Upgrading all modules on PROD..."
    MODULES=$(ls -1 "$DEV_ADDONS" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    if [ -n "$MODULES" ]; then
        ssh -i "$SSH_KEY" "$SSH_USER@$SERVER" "docker exec odoo-prod odoo -d $CLIENT -u $MODULES --stop-after-init --no-http"
    fi
fi

echo "3. Restarting PROD Odoo..."
ssh -i "$SSH_KEY" "$SSH_USER@$SERVER" "docker restart odoo-prod"

echo ""
echo "=== Deploy complete ==="
echo "Modules pushed to $SERVER:$PROD_DIR/addons/"
[ -n "$MODULE" ] && echo "Module $MODULE upgraded" || echo "All modules upgraded"
