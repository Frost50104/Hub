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
#   HEALTHCHECK_DISK_PATH=/
#   HEALTHCHECK_DISK_MIN_GB=8
#   HEALTHCHECK_HR_URLS="https://hub.signaris.ru/api/health/hr"
set -euo pipefail

URLS=${HEALTHCHECK_URLS:-"https://hub.signaris.ru/api/env https://hub-staging.signaris.ru/api/env"}
# Отдельный список: у этих ручек мало вернуть 200 — важно СОДЕРЖИМОЕ. Web push
# в Hub однажды не работал месяц при полностью здоровом /api/env: сломался
# только транспорт, и снаружи это было неотличимо от «никому не писали»
# (инцидент 26.08).
PUSH_URLS=${HEALTHCHECK_PUSH_URLS:-"https://hub.signaris.ru/api/health/push https://hub-staging.signaris.ru/api/health/push"}
# Свободное место. До 15.09 проверки диска здесь не было вообще, а
# единственной защитой оставался statvfs-порог на загрузке медиа — то есть о
# заканчивающемся диске узнавали бы в момент, когда сотрудник уже получил отказ.
# С видео во вложениях (до 1 ГБ на файл) это перестало быть приемлемым.
#
# 8 ГБ — выше порога отказа загрузки (5 ГБ + размер файла), чтобы алерт пришёл
# ДО того, как загрузки начнут отбиваться, а не вместе с ними.
# Кадровые данные из auth (16d). Только прод: на staging синк штата выключен
# навсегда, строк состояния там нет.
HR_URLS=${HEALTHCHECK_HR_URLS:-"https://hub.signaris.ru/api/health/hr"}
DISK_PATH=${HEALTHCHECK_DISK_PATH:-/}
DISK_MIN_GB=${HEALTHCHECK_DISK_MIN_GB:-8}
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

# --- Свободное место на диске ----------------------------------------------
# Диск общий с Postgres/WAL: переполнение это не «не загрузился файл», а
# остановка базы. Триггер краевой (состояние в файле) — иначе при нехватке
# места алерт уходил бы каждые 5 минут, и его перестали бы читать.
disk_state="$STATE_DIR/disk.$(slug "$DISK_PATH").state"
disk_prev=$(cat "$disk_state" 2>/dev/null || echo 0)
# `df -Pk` — POSIX-формат: одна строка на точку монтирования даже при длинном
# имени устройства, значение в килобайтах.
free_kb=$(df -Pk "$DISK_PATH" 2>/dev/null | awk 'NR==2 {print $4}')
if [[ -n "${free_kb:-}" ]]; then
  free_gb=$((free_kb / 1024 / 1024))
  if [[ "$free_gb" -lt "$DISK_MIN_GB" ]]; then
    echo 1 > "$disk_state"
    logger -t signaris-hub-health "DISK LOW $DISK_PATH (${free_gb}G free, min ${DISK_MIN_GB}G)"
    if [[ "$disk_prev" == "0" ]]; then
      send_telegram "🔴 [Hub] мало места на диске: $DISK_PATH — свободно ${free_gb} ГБ (порог ${DISK_MIN_GB} ГБ). Загрузка вложений скоро начнёт отбиваться."
    fi
  else
    if [[ "$disk_prev" != "0" ]]; then
      logger -t signaris-hub-health "DISK RECOVERED $DISK_PATH (${free_gb}G free)"
      send_telegram "✅ [Hub] с местом на диске снова порядок: $DISK_PATH — свободно ${free_gb} ГБ"
    fi
    echo 0 > "$disk_state"
  fi
fi

# --- Кадровые данные из auth -----------------------------------------------
# Ручка отдаёт {"status": "ok"|"attention", "problems": [...]}: коды без
# названий организаций. Каждый код значит «правка кадров в Hub закрыта, а из
# auth ничего не приходит». Триггер — по СМЕНЕ набора проблем: одно сообщение
# при появлении, одно при исправлении, без повтора каждые 5 минут.
hr_text() {
  local out=""
  for code in $(echo "$1" | tr ',' ' '); do
    case "$code" in
      window_open) out+="окно каткатa открыто больше 6 ч (закройте: hr_cutover --window close); " ;;
      blocked) out+="предохранитель держит изменения больше часа (hub-admin: «Сотрудники» → «Посмотреть и применить»); " ;;
      paused) out+="организация заморожена, но применение не включено больше часа (SIGNARIS_HUB_HR_APPLY_TENANTS); " ;;
      stale) out+="успешного применения не было больше часа (auth недоступен или сбой — журнал hr_sync); " ;;
      *) out+="$code; " ;;
    esac
  done
  echo "$out"
}

for url in $HR_URLS; do
  state_file="$STATE_DIR/hr.$(slug "$url").state"
  prev=$(cat "$state_file" 2>/dev/null || echo "")
  body=$(curl -fs --max-time 10 "$url" 2>/dev/null || echo "")
  # Недоступность самой ручки ловит проверка /api/env выше.
  [[ -n "$body" ]] || continue
  problems=$(echo "$body" | sed -n 's/.*"problems":[[:space:]]*\[\([^]]*\)\].*/\1/p' | tr -d '" ')
  [[ "$problems" == "$prev" ]] && continue
  echo "$problems" > "$state_file"
  if [[ -z "$problems" ]]; then
    logger -t signaris-hub-health "HR RECOVERED $url"
    send_telegram "✅ [Hub] кадровые данные из auth снова в порядке: $url"
  else
    logger -t signaris-hub-health "HR ATTENTION $url ($problems)"
    send_telegram "🔴 [Hub] кадровые данные из auth: $(hr_text "$problems")— $url"
  fi
done
