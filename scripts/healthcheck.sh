#!/usr/bin/env bash
# Curl https://hub.signaris.ru/api/env every 5 min via systemd timer.
# Alert (`mail -s ...`) after N consecutive failures so a single flap doesn't
# spam ops. State file holds the running counter; reset to 0 on success.
#
# Configurable via env (default works as-is):
#   HEALTHCHECK_URLS="https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"
#   HEALTHCHECK_ALERT_EMAIL=ops@signaris.ru
#   HEALTHCHECK_FAILURES_BEFORE_ALERT=2
set -euo pipefail

URLS=${HEALTHCHECK_URLS:-"https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"}
EMAIL=${HEALTHCHECK_ALERT_EMAIL:-ops@signaris.ru}
THRESHOLD=${HEALTHCHECK_FAILURES_BEFORE_ALERT:-2}
STATE_DIR=/var/lib/signaris-hub
mkdir -p "$STATE_DIR"

slug() {
  echo "$1" | sed 's![:/]!_!g'
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
    fi
  fi
done
