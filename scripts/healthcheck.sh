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
#   HEALTHCHECK_PUSH_URLS="https://hub.signaris.ru/api/health/push ..."
set -euo pipefail

URLS=${HEALTHCHECK_URLS:-"https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"}
# Отдельный список: у этих ручек мало вернуть 200 — важно СОДЕРЖИМОЕ. Web push
# в Hub однажды не работал месяц при полностью здоровом /api/env: сломался
# только транспорт, и снаружи это было неотличимо от «никому не писали»
# (инцидент 26.08).
PUSH_URLS=${HEALTHCHECK_PUSH_URLS:-"https://hub.signaris.ru/api/health/push https://hub-staging.signaris.ru/api/health/push"}
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

# --- Транспорт уведомлений -------------------------------------------------
# Ручка отдаёт {"vapid": "ok"|"absent"|"invalid"|"mismatch"}. Всё, кроме "ok",
# означает, что пуши не уходят, — и об этом надо узнавать в тот же день, а не
# по жалобе через месяц.
for url in $PUSH_URLS; do
  state_file="$STATE_DIR/push.$(slug "$url").state"
  prev=$(cat "$state_file" 2>/dev/null || echo 0)
  body=$(curl -fs --max-time 10 "$url" 2>/dev/null || echo "")
  if echo "$body" | grep -q '"vapid":[[:space:]]*"ok"'; then
    if [[ "$prev" != "0" ]]; then
      logger -t signaris-hub-health "PUSH RECOVERED $url"
      send_telegram "✅ [Hub] push-транспорт снова в порядке: $url"
    fi
    echo 0 > "$state_file"
  else
    new=$((prev + 1))
    echo "$new" > "$state_file"
    status=$(echo "$body" | sed -n 's/.*"vapid":[[:space:]]*"\([a-z]*\)".*/\1/p')
    logger -t signaris-hub-health "PUSH FAIL $url (vapid=${status:-unreachable}, consecutive=$new)"
    if [[ "$new" -ge "$THRESHOLD" ]] && [[ "$prev" -lt "$THRESHOLD" ]]; then
      send_telegram "🔴 [Hub] push НЕ РАБОТАЕТ: $url — vapid=${status:-unreachable}"
    fi
  fi
done
