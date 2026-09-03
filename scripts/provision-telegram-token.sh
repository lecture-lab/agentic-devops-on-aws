#!/usr/bin/env bash
# Put the Telegram bot token into Secrets Manager without it ever
# appearing as a command-line argument (visible via `ps` to anyone
# sharing this host's UID -- confirmed a real exposure surface here,
# not a hypothetical one).
#
# Usage: read the token on stdin, it never touches argv or shell history.
#   provision-telegram-token.sh < token.txt
#   printf '%s' "$TOKEN" | provision-telegram-token.sh
set -euo pipefail

SECRET_ID="agentic-devops-dev/telegram-bot-token"
REGION="ap-northeast-2"

TMP_FILE="$(mktemp)"
trap 'shred -u "$TMP_FILE" 2>/dev/null || rm -f "$TMP_FILE"' EXIT
chmod 600 "$TMP_FILE"

cat > "$TMP_FILE"

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ID" \
  --secret-string "file://$TMP_FILE" \
  --region "$REGION" \
  --query '{Name:Name,VersionId:VersionId}' \
  --output json

echo "Stored. Value never appeared in argv or shell history." >&2
