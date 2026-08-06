#!/usr/bin/env bash
# Deterministic fixture test for 04-generate-alertmanager-config.sh.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$SCRIPT_DIR")
FIXTURE=$(mktemp -d)
trap 'rm -rf "$FIXTURE"' EXIT

TOKEN='1234567890:fixture-token-never-committed'
CHAT_ID='987654321'
cp "$ROOT/monitoring/alertmanager/alertmanager.yml.template" "$FIXTURE/template.yml"
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT_ID" > "$FIXTURE/secrets"
chmod 0755 "$FIXTURE"

"$SCRIPT_DIR/04-generate-alertmanager-config.sh" \
    --template "$FIXTURE/template.yml" \
    --output "$FIXTURE/output.yml" \
    --secrets-file "$FIXTURE/secrets" >/dev/null

mode=$(stat -c '%a' "$FIXTURE/output.yml")
[ "$mode" = 644 ] || { echo "wrong output mode: $mode" >&2; exit 1; }
grep -Fq "bot_token: \"$TOKEN\"" "$FIXTURE/output.yml"
grep -Fq "chat_id: $CHAT_ID" "$FIXTURE/output.yml"
if git -C "$ROOT" grep -Fq "$TOKEN" -- .; then
    echo "fixture secret appeared in a tracked file" >&2
    exit 1
fi

if command -v amtool >/dev/null 2>&1; then
    amtool check-config "$FIXTURE/output.yml" >/dev/null
else
    docker run --rm --entrypoint amtool -v "$FIXTURE:/fixture:ro" prom/alertmanager:v0.33.1 \
        check-config /fixture/output.yml >/dev/null
fi
echo "Alertmanager generator fixture test passed"
