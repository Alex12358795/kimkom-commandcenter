#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -eq 3 ]] || { printf 'usage: %s ENV_FILE KEY VALUE\n' "$0" >&2; exit 64; }
env_file=$1
key=$2
value=$3
case "$key" in
    MANAGEMENT_BIND_IP)
        [[ "$value" =~ ^[0-9a-fA-F:.]+$ ]] || { printf 'invalid bind address\n' >&2; exit 64; }
        ;;
    GRAFANA_PASSWORD)
        [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != --unset ]] || {
            printf 'invalid Grafana password\n' >&2
            exit 64
        }
        ;;
    *) printf 'unsupported runtime key\n' >&2; exit 64 ;;
esac
[[ -f "$env_file" ]] || { printf 'environment file not found\n' >&2; exit 1; }

temporary=$(mktemp "${env_file}.new.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
found=false
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "$key="* && "$value" == --unset ]]; then
        found=true
    elif [[ "$line" == "$key="* ]]; then
        printf "%s='%s'\n" "$key" "$value" >> "$temporary"
        found=true
    else
        printf '%s\n' "$line" >> "$temporary"
    fi
done < "$env_file"
if [[ "$found" != true && "$value" != --unset ]]; then
    printf "%s='%s'\n" "$key" "$value" >> "$temporary"
fi
chmod 0600 "$temporary"
mv -f -- "$temporary" "$env_file"
trap - EXIT
