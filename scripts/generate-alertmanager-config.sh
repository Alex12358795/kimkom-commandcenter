#!/usr/bin/env bash
# Generate alertmanager.yml from template with secrets injected
# Obtain bot token from @BotFather and chat ID from @get_id_bot on Telegram

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE="$CC_ROOT/monitoring/alertmanager/alertmanager.yml.template"
OUTPUT="$CC_ROOT/monitoring/alertmanager/alertmanager.yml"
SECRETS_FILE="$CC_ROOT/secrets/commandcenter/alertmanager-secrets"

if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template not found at $TEMPLATE"
    exit 1
fi

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

if [ -f "$SECRETS_FILE" ]; then
    source "$SECRETS_FILE"
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

sed "s/__TELEGRAM_BOT_TOKEN__/$TELEGRAM_BOT_TOKEN/g; s/chat_id: 0/chat_id: $TELEGRAM_CHAT_ID/g" "$TEMPLATE" > "$OUTPUT"
chmod 640 "$OUTPUT"
echo "Generated $OUTPUT"
echo "Run: docker compose -f monitoring/docker-compose.yml --env-file .env up -d --force-recreate alertmanager"