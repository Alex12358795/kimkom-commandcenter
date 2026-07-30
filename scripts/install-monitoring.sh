#!/usr/bin/env bash
# install-monitoring.sh — Add Prometheus exporters to an existing KimKom-stack VM.
# Idempotent: run again to fix bind IP or update CC targets.
#
# Usage: install-monitoring.sh --client-slug SLUG --target-ts-ip TS_IP
#
# Does:
#   1. Ensure node-exporter + postgres-exporter services in docker-compose.yaml
#   2. Fix MANAGEMENT_BIND_IP in .env (set to 0.0.0.0 for Tailscale scrape)
#   3. Recreate exporters
#   4. Verify scrape endpoints are reachable from CommandCenter
#   5. Add Prometheus targets on CommandCenter (nodes.yml + postgres.yml)
#   6. Reload Prometheus

set -Eeuo pipefail

# --- Defaults -----------------------------------------------------------
SSH_KEY="${SSH_KEY:-/opt/kimkom-commandcenter/ssh/deploy_key}"
SSH_USER="${SSH_USER:-alex}"
STACK_ROOT="${STACK_ROOT:-/opt/kimkom-commandcenter}/.."
PROMETHEUS_TARGETS_DIR="${PROMETHEUS_TARGETS_DIR:-/opt/kimkom-commandcenter/monitoring/prometheus/targets}"

# --- Help ---------------------------------------------------------------
usage() {
    sed -n '2,15p' "$0"
    exit 1
}

# --- Argument parsing ---------------------------------------------------
client_slug=
ts_ip=

while (($#)); do
    case $1 in
        --client-slug)    client_slug=$2; shift 2 ;;
        --target-ts-ip)   ts_ip=$2;       shift 2 ;;
        -h|--help)        usage ;;
        *) usage ;;
    esac
done

[[ -n "${client_slug:-}" ]] || { echo "ERROR: --client-slug required" >&2; usage; }
[[ -n "${ts_ip:-}" ]]      || { echo "ERROR: --target-ts-ip required" >&2; usage; }

stack_dir="/opt/kimkom-${client_slug}"

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${SSH_USER}@${ts_ip}")

# --- Banner -------------------------------------------------------------
cat <<EOF

=== install-monitoring ===
Client slug:    $client_slug
Target (TS):    $ts_ip
Stack on target: $stack_dir
========================

EOF

# --- Step 1: Ensure services in docker-compose.yaml ---------------------
printf '[1/6] check docker-compose.yaml for exporters...\n'

have_node=$( "${SSH[@]}" "grep -c '^  node-exporter:' '$stack_dir/docker-compose.yaml' 2>/dev/null" || echo 0 )
have_pg=$(   "${SSH[@]}" "grep -c '^  postgres-exporter:' '$stack_dir/docker-compose.yaml' 2>/dev/null" || echo 0 )

if [[ "$have_node" -eq 0 || "$have_pg" -eq 0 ]]; then
    echo "ERROR: node-exporter or postgres-exporter not found in docker-compose.yaml" >&2
    echo "Ensure the KimKom-stack docker-compose.yaml is up to date (should include both services)." >&2
    exit 1
fi
echo "  Exporters already defined in docker-compose.yaml"

# --- Step 2: Fix MANAGEMENT_BIND_IP -------------------------------------
printf '\n[2/6] ensure MANAGEMENT_BIND_IP allows Tailscale scrape...\n'

current_bind=$( "${SSH[@]}" "grep '^MANAGEMENT_BIND_IP=' '$stack_dir/.env' 2>/dev/null" || echo "" )

if [[ "$current_bind" == *"0.0.0.0"* ]]; then
    echo "  MANAGEMENT_BIND_IP already 0.0.0.0 — skip"
elif [[ -z "$current_bind" ]]; then
    echo "  MANAGEMENT_BIND_IP not set — adding as 0.0.0.0"
    "${SSH[@]}" "echo \"MANAGEMENT_BIND_IP='0.0.0.0'\" >> '$stack_dir/.env'"
else
    printf '  MANAGEMENT_BIND_IP=%s → fixing to 0.0.0.0\n' "$current_bind"
    "${SSH[@]}" "sed -i \"s|^MANAGEMENT_BIND_IP=.*|MANAGEMENT_BIND_IP='0.0.0.0'|\" '$stack_dir/.env'"
fi

# --- Step 3: Recreate exporter containers --------------------------------
printf '\n[3/6] recreate exporters...\n'

"${SSH[@]}" bash -s -- "$stack_dir" <<'REMOTE'
set -Eeuo pipefail
stack=$1
cd "$stack"
docker compose --env-file .env up -d --force-recreate node-exporter postgres-exporter
REMOTE

printf '  Exporters recreated\n'

# --- Step 4: Verify scrape endpoints ------------------------------------
printf '\n[4/6] verify scrape endpoints...\n'

node_ok=0
pg_ok=0

for i in $(seq 1 15); do
    if curl -sSf --connect-timeout 3 "http://${ts_ip}:9100/metrics" -o /dev/null 2>/dev/null; then
        node_ok=1
        break
    fi
    sleep 2
done

for i in $(seq 1 15); do
    if curl -sSf --connect-timeout 3 "http://${ts_ip}:9187/metrics" -o /dev/null 2>/dev/null; then
        pg_ok=1
        break
    fi
    sleep 2
done

node_status="REACHABLE"
pg_status="REACHABLE"
if [[ "$node_ok" -ne 1 ]]; then node_status="UNREACHABLE"; fi
if [[ "$pg_ok" -ne 1 ]];   then pg_status="UNREACHABLE"; fi

printf '  node_exporter      %s:9100 → %s\n' "$ts_ip" "$node_status"
printf '  postgres_exporter  %s:9187 → %s\n' "$ts_ip" "$pg_status"

if [[ "$node_ok" -ne 1 || "$pg_ok" -ne 1 ]]; then
    echo "WARNING: one or more scrape endpoints unreachable" >&2
    echo "Check that Tailscale is working and the VM allows inbound on these ports." >&2
fi

# --- Step 5: Add Prometheus targets on CommandCenter --------------------
printf '\n[5/6] update Prometheus targets on CommandCenter...\n'

need_reload=0

add_target() {
    local target_file=$1 target_addr=$2 environment=$3 client=$4 transport=$5

    # Check if this target already exists in the file
    if grep -qF "\"${target_addr}\"" "$target_file" 2>/dev/null; then
        echo "  Target ${target_addr} already present in $(basename "$target_file") — skip"
        return 0
    fi

    echo "  Adding ${target_addr} to $(basename "$target_file")..."

    # Append a new target block
    cat >> "$target_file" <<YAML
- targets:
    - "${target_addr}"
  labels:
    client: "${client}"
    environment: "${environment}"
YAML
    if [[ -n "${transport:-}" ]]; then
        echo "    transport: \"${transport}\"" >> "$target_file"
    fi

    need_reload=1
}

add_target "$PROMETHEUS_TARGETS_DIR/nodes.yml"    "${ts_ip}:9100" pilot "$client_slug" tailscale
add_target "$PROMETHEUS_TARGETS_DIR/postgres.yml" "${ts_ip}:9187" pilot "$client_slug" tailscale

# --- Step 6: Reload Prometheus ------------------------------------------
printf '\n[6/6] reload Prometheus...\n'

if [[ "$need_reload" -eq 1 ]]; then
    cd /opt/kimkom-commandcenter
    docker compose -f monitoring/docker-compose.yml --env-file .env restart prometheus >/dev/null 2>&1
    echo "  Prometheus restarted to pick up new targets"
else
    echo "  No target changes — skip Prometheus reload"
fi

# --- Done ---------------------------------------------------------------
cat <<EOF

=== Install complete ===
  node_exporter:      ${ts_ip}:9100
  postgres_exporter:  ${ts_ip}:9187
  Environment:        pilot
  Client:             ${client_slug}

Prometheus targets in:
  ${PROMETHEUS_TARGETS_DIR}/nodes.yml
  ${PROMETHEUS_TARGETS_DIR}/postgres.yml

Alerts are filtered to production only; pilot alerts are muted in Alertmanager.
EOF
