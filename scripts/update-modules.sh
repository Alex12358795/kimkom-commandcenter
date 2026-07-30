#!/usr/bin/env bash
# update-modules.sh — sync Odoo modules from CommandCenter to a customer VM
# over Tailscale, then trigger `odoo -u` on the customer. No image rebuild
# required: the modules live as a bind-mounted volume on the customer VM.
#
# Source of truth: /opt/kimkom-modules/<slug>/ on CommandCenter (still git-tracked
# against the kimkom-modules repo).
# Target:          /opt/kimkom-stack/modules/ on the customer VM.
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Source client-config.sh if it exists (for slug/stack validation).
if [[ -r "$SCRIPT_DIR/lib/client-config.sh" ]]; then
    # shellcheck source=lib/client-config.sh
    source "$SCRIPT_DIR/lib/client-config.sh"
fi

usage() {
    cat <<'EOF'
Usage: update-modules.sh --slug SLUG --target-ts-ip IP [options]
  --slug SLUG            Client slug (e.g. supertcg); sources /opt/kimkom-modules/<slug>/
  --target-ts-ip IP      Customer VM Tailscale IP
  --upgrade-modules CSV  Comma-separated module list, or "all" (default: all)
  --stack-dir PATH       Customer stack directory (default: /opt/kimkom-<slug>)
  --modules-source PATH  Override modules source on CommandCenter
  --modules-target PATH  Override modules target on customer VM (default: <stack>/modules)
  --ssh-user USER        SSH user (default: alex)
  --ssh-key PATH         SSH key (default: <script-dir>/ssh/deploy_key)
  --skip-recovery-point  Skip the pre-upgrade recovery point (NOT recommended)
  --dry-run              Print plan without changes
  --help                 Show this message
EOF
}

slug= ts_ip= modules=
stack_dir= src= dst=
user=alex
key="$SCRIPT_DIR/../ssh/deploy_key"
skip_rp=false
dry=false

while (($#)); do
    case "$1" in
        --slug)              [[ -n "${2-}" ]] || { echo "--slug requires a value" >&2; exit 2; }; slug=$2; shift 2 ;;
        --target-ts-ip)      [[ -n "${2-}" ]] || { echo "--target-ts-ip requires a value" >&2; exit 2; }; ts_ip=$2; shift 2 ;;
        --upgrade-modules)   [[ -n "${2-}" ]] || { echo "--upgrade-modules requires a value" >&2; exit 2; }; modules=$2; shift 2 ;;
        --stack-dir)         [[ -n "${2-}" ]] || { echo "--stack-dir requires a value" >&2; exit 2; }; stack_dir=$2; shift 2 ;;
        --modules-source)    [[ -n "${2-}" ]] || { echo "--modules-source requires a value" >&2; exit 2; }; src=$2; shift 2 ;;
        --modules-target)    [[ -n "${2-}" ]] || { echo "--modules-target requires a value" >&2; exit 2; }; dst=$2; shift 2 ;;
        --ssh-user)          [[ -n "${2-}" ]] || { echo "--ssh-user requires a value" >&2; exit 2; }; user=$2; shift 2 ;;
        --ssh-key)           [[ -n "${2-}" ]] || { echo "--ssh-key requires a value" >&2; exit 2; }; key=$2; shift 2 ;;
        --skip-recovery-point) skip_rp=true; shift ;;
        --dry-run)           dry=true; shift ;;
        --help|-h)           usage; exit 0 ;;
        *)                   echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -n "$slug" ]]   || { echo "--slug is required" >&2; exit 2; }
[[ -n "$ts_ip" ]]  || { echo "--target-ts-ip is required" >&2; exit 2; }
modules=${modules:-all}

# Optional slug validation if lib/client-config.sh is loaded.
if declare -F validate_client_slug >/dev/null 2>&1; then
    validate_client_slug "$slug" || { echo "invalid slug: $slug" >&2; exit 2; }
fi

# Resolve defaults.
stack_dir=${stack_dir:-/opt/kimkom-${slug}}
src=${src:-/opt/kimkom-modules/${slug}}
dst=${dst:-${stack_dir}/modules}

# Validate SSH key.
[[ -r "$key" ]] || { echo "SSH key not readable: $key" >&2; exit 2; }

SSH=(ssh -i "$key" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 \
        -o BatchMode=yes "$user@$ts_ip")
RSYNC_SSH=(ssh -i "$key" -o StrictHostKeyChecking=accept-new -o BatchMode=yes)

# Banner.
printf '\n=== update-modules ===\n'
printf 'Slug:            %s\n' "$slug"
printf 'Target (TS):     %s\n' "$ts_ip"
printf 'Stack on target: %s\n' "$stack_dir"
printf 'Modules source:  %s\n' "$src"
printf 'Modules target:  %s\n' "$dst"
printf 'Modules upgrade: %s\n' "$modules"
printf 'Recovery point:  %s\n' "$([[ $skip_rp == true ]] && echo SKIP || echo CREATE)"
printf '======================\n'

if [[ "$dry" == true ]]; then
    printf '\nDry run: no rsync, no SSH mutation, no module upgrade.\n'
    exit 0
fi

# Pre-flight: confirm source + target reachability.
[[ -d "$src" ]] || { echo "modules source not found: $src" >&2; exit 1; }
"${SSH[@]}" true || { echo "SSH to $ts_ip failed" >&2; exit 1; }

# Confirm Odoo is running on the target before we touch anything.
remote_odoo_up() {
    "${SSH[@]}" bash -s -- "$stack_dir" <<'REMOTE'
set -Eeuo pipefail
stack=$1
cd "$stack"
container=$(docker compose -f docker-compose.yaml --env-file .env ps -q odoo 2>/dev/null | awk 'NF{print;exit}')
if [[ -z "$container" ]]; then
    echo "ERROR: odoo container not running on target" >&2
    exit 1
fi
echo "odoo container: $container"
REMOTE
}
remote_odoo_up || exit 1

# Step 1: rsync modules to a staging dir on the customer VM.
# Use --delete to mirror exactly the source state (no drift).
printf '\n[1/4] rsync modules to staging...\n'
"${SSH[@]}" mkdir -p "${dst}.staging"
rsync -a --delete --no-perms --no-owner --no-group \
    -e "$(printf '%q ' "${RSYNC_SSH[@]}")" \
    --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' \
    "$src/" "$user@$ts_ip:${dst}.staging/" \
    || { echo "rsync failed" >&2; exit 1; }

# Step 2: create a recovery point on the customer VM before mutating modules.
# This mirrors what update.sh does: quiesced paired DB+filestore snapshot.
recovery_id=
if [[ $skip_rp != true ]]; then
    printf '\n[2/4] create recovery point on target...\n'
    recovery=$("${SSH[@]}" bash -s -- "$stack_dir" "$slug" "$modules" <<'REMOTE'
set -Eeuo pipefail
stack=$1; slug=$2; modules=$3
recovery=/usr/local/libexec/kimkom-backup-v2
if [[ ! -x "$recovery/recovery-point.sh" ]]; then
    echo "SKIP: recovery-point.sh not installed on target" >&2
    exit 0
fi
old_sha=$(git -C "$stack" rev-parse HEAD 2>/dev/null || echo unknown)
current=$(docker compose -f "$stack/docker-compose.yaml" --env-file "$stack/.env" ps -q odoo 2>/dev/null | awk 'NF{print;exit}')
old_image=$(docker inspect --format='{{index .Config.Image}}' "$current" 2>/dev/null || echo unknown)
# sudo required: recovery-point.sh needs Restic and DB access.
sudo -n "$recovery/recovery-point.sh" create \
    --expected-git-sha "$old_sha" \
    --expected-image "$old_image" \
    --modules "$modules"
REMOTE
)
    recovery_id="$recovery"
    printf 'Recovery point: %s\n' "$recovery_id"
    if [[ -z "$recovery_id" || "$recovery_id" == *"SKIP"* ]]; then
        echo "WARNING: proceeding without recovery point" >&2
        recovery_id=
    fi
fi

# Step 3: atomic swap of modules + chown to odoo UID (100:101).
printf '\n[3/4] swap modules and chown...\n'
"${SSH[@]}" bash -s -- "$dst" <<'REMOTE'
set -Eeuo pipefail
dst=$1
# Atomic move: rename old → .old, staging → main, then remove .old.
rm -rf "$dst.old" 2>/dev/null || true
if [[ -d "$dst" ]]; then
    mv "$dst" "$dst.old"
fi
mv "$dst.staging" "$dst"
rm -rf "$dst.old"
# Odoo runs as uid 100 inside the container.
sudo chown -R 100:101 "$dst"
sudo chmod -R u+rwX,go+rX "$dst"
echo "modules dir swapped and chowned"
REMOTE

# Step 4: trigger Odoo upgrade.
printf '\n[4/4] run odoo -u %s on target...\n' "$modules"
upgrade_rc=0
"${SSH[@]}" bash -s -- "$stack_dir" "$modules" <<'REMOTE' || upgrade_rc=$?
set -Eeuo pipefail
stack=$1; modules=$2
cd "$stack"
docker compose -f docker-compose.yaml --env-file .env stop odoo
docker compose -f docker-compose.yaml --env-file .env run --rm -T odoo \
    odoo -u "$modules" --stop-after-init --no-http </dev/null
docker compose -f docker-compose.yaml --env-file .env up -d --no-deps --force-recreate odoo
container=$(docker compose -f docker-compose.yaml --env-file .env ps -q odoo | awk 'NF{print;exit}')
for i in $(seq 1 60); do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo unknown)
    if [[ "$status" == "healthy" ]]; then
        echo "odoo healthy after $((i*2))s"
        exit 0
    fi
    sleep 2
done
echo "ERROR: odoo did not become healthy within 120s" >&2
docker logs --tail 100 "$container" >&2 || true
exit 1
REMOTE

if ((upgrade_rc != 0)); then
    echo "FAILED: odoo upgrade exit=$upgrade_rc" >&2
    if [[ -n "$recovery_id" ]]; then
        echo "Restore from recovery point:" >&2
        echo "  ssh $user@$ts_ip 'sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh prepare --id $recovery_id'" >&2
        echo "  ssh $user@$ts_ip 'sudo /usr/local/libexec/kimkom-backup-v2/restore-recovery-point.sh apply --id $recovery_id --confirm-id $recovery_id'" >&2
    fi
    exit 1
fi

printf '\nModule upgrade complete on %s.\n' "$ts_ip"
if [[ -n "$recovery_id" ]]; then
    printf 'Recovery point retained: %s\n' "$recovery_id"
fi
