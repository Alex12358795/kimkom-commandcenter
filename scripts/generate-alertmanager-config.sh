#!/usr/bin/env bash
# Generate alertmanager.yml from an ignored secrets file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE="$CC_ROOT/monitoring/alertmanager/alertmanager.yml.template"
OUTPUT="$CC_ROOT/monitoring/alertmanager/alertmanager.yml"
SECRETS_FILE="$CC_ROOT/secrets/commandcenter/alertmanager-secrets"

usage() {
    echo "Usage: $0 [--template FILE] [--output FILE] [--secrets-file FILE]"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --template) TEMPLATE=${2:?missing value for --template}; shift 2 ;;
        --output) OUTPUT=${2:?missing value for --output}; shift 2 ;;
        --secrets-file) SECRETS_FILE=${2:?missing value for --secrets-file}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template not found at $TEMPLATE"
    exit 1
fi

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

# Read values, rather than sourcing the file: a secrets file must not be able
# to execute shell code. Only these two assignment keys are accepted.
if [ -f "$SECRETS_FILE" ]; then
    while IFS='=' read -r key value || [ -n "${key:-}" ]; do
        key=${key//$'\r'/}
        value=${value//$'\r'/}
        case "$key" in
            TELEGRAM_BOT_TOKEN) TELEGRAM_BOT_TOKEN=$value ;;
            TELEGRAM_CHAT_ID) TELEGRAM_CHAT_ID=$value ;;
            ''|\#*) ;;
            *) echo "ERROR: unsupported key in $SECRETS_FILE: $key" >&2; exit 1 ;;
        esac
    done < "$SECRETS_FILE"
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN is not set."
    echo "Create $SECRETS_FILE with:"
    echo "  TELEGRAM_BOT_TOKEN=<your-bot-token>"
    echo "  TELEGRAM_CHAT_ID=<your-chat-id>"
    echo ""
    echo "Instructions:"
    echo "  1. Message @BotFather on Telegram to create a bot"
    echo "  2. Copy the bot token"
    echo "  3. Message @get_id_bot on Telegram to get your chat ID"
    echo "  4. Fill in $SECRETS_FILE"
    exit 1
fi

if [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo "ERROR: TELEGRAM_CHAT_ID is not set."
    exit 1
fi

if [[ ! "$TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]]; then
    echo "ERROR: TELEGRAM_CHAT_ID must be an integer." >&2
    exit 1
fi

# Refuse to put a secret into an indexed path. This remains useful protection
# if the ignore rule is accidentally removed in the future.
if git -C "$CC_ROOT" ls-files --error-unmatch -- "$OUTPUT" >/dev/null 2>&1; then
    echo "ERROR: refusing to write tracked Alertmanager config: $OUTPUT" >&2
    echo "Untrack it with: git rm --cached -- monitoring/alertmanager/alertmanager.yml" >&2
    exit 1
fi

OUTPUT_DIR=$(dirname "$OUTPUT")
mkdir -p "$OUTPUT_DIR"
TEMP_OUTPUT=$(mktemp "$OUTPUT.tmp.XXXXXX")
trap 'rm -f "$TEMP_OUTPUT"' EXIT
awk -v token="$TELEGRAM_BOT_TOKEN" -v chat_id="$TELEGRAM_CHAT_ID" \
    '{ gsub(/__TELEGRAM_BOT_TOKEN__/, token); gsub(/chat_id: 0/, "chat_id: " chat_id); print }' \
    "$TEMPLATE" > "$TEMP_OUTPUT"
chmod 0644 "$TEMP_OUTPUT"
mv -f "$TEMP_OUTPUT" "$OUTPUT"
trap - EXIT
echo "Generated $OUTPUT"
echo "Run: docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager"
