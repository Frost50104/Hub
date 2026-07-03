#!/usr/bin/env bash
# Curl https://hub.signaris.ru/api/env every 5 min via systemd timer.
# Alert after N consecutive failures so a single flap doesn't spam ops.
# State file holds the running counter; reset to 0 on success.
# Channels: `mail -s ...` (needs an MTA) and/or Telegram Bot API — each is
# skipped silently when not configured, so the probe itself always runs.
#
# Configurable via env (default works as-is):
#   HEALTHCHECK_URLS="https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"
#   HEALTHCHECK_ALERT_EMAIL=ops@signaris.ru
#   HEALTHCHECK_FAILURES_BEFORE_ALERT=2
#   TELEGRAM_BOT_TOKEN=123456:ABC-...   (from @BotFather; empty = Telegram off)
#   TELEGRAM_CHAT_ID=-100123456789
set -euo pipefail

URLS=${HEALTHCHECK_URLS:-"https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"}
EMAIL=${HEALTHCHECK_ALERT_EMAIL:-ops@signaris.ru}
THRESHOLD=${HEALTHCHECK_FAILURES_BEFORE_ALERT:-2}
TG_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TG_CHAT=${TELEGRAM_CHAT_ID:-}
STATE_DIR=/var/lib/signaris-hub
mkdir -p "$STATE_DIR"

slug() {
  echo "$1" | sed 's![:/]!_!g'
}

send_telegram() {
  # $1 = message text. No-op unless both token and chat id are set.
  [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]] || return 0
  curl -fs --max-time 10 -X POST \
    "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT}" \
    --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

for url in $URLS; do
  state_file="$STATE_DIR/health.$(slug "$url").state"
  prev=$(cat "$state_file" 2>/dev/null || echo 0)
  if curl -fs --max-time 10 "$url" >/dev/null 2>&1; then
    if [[ "$prev" != "0" ]]; then
      # Recovered — log it; reset counter; alert recovery email.
      logger -t signaris-hub-health "RECOVERED $url after $prev failures"
      if command -v mail >/dev/null 2>&1; then
        echo "Hub healthcheck RECOVERED: $url after $prev failed probes" \
          | mail -s "[Hub] healthcheck OK: $url" "$EMAIL" || true
      fi
      send_telegram "✅ [Hub] healthcheck OK: $url (after $prev failed probes)"
    fi
    echo 0 > "$state_file"
  else
    new=$((prev + 1))
    echo "$new" > "$state_file"
    logger -t signaris-hub-health "FAIL $url (consecutive=$new)"
    if [[ "$new" -ge "$THRESHOLD" ]] && [[ "$prev" -lt "$THRESHOLD" ]]; then
      # Edge-trigger: first time we cross the threshold, send one email.
      if command -v mail >/dev/null 2>&1; then
        echo "Hub healthcheck FAIL: $url ($new consecutive failures)" \
          | mail -s "[Hub] healthcheck DOWN: $url" "$EMAIL" || true
      fi
      send_telegram "🔴 [Hub] healthcheck DOWN: $url ($new consecutive failures)"
    fi
  fi
done
