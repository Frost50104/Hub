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
#   HEALTHCHECK_RACE_URLS="https://hub.signaris.ru/api/health/race"
#   HEALTHCHECK_STT_UNIT=signaris-hub-stt.service   (проверяется, только если включён)
#   HEALTHCHECK_STT_URL=http://127.0.0.1:5071/health
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
# «Гусиная гонка» (02.10, перед боевым стартом 05.10). Только прод: на staging
# обращения к iiko выключены флагом, ручка отвечает status=disabled. Дефолт
# обязателен — под `set -u` пустая переменная уронила бы ВЕСЬ скрипт.
RACE_URLS=${HEALTHCHECK_RACE_URLS:-"https://hub.signaris.ru/api/health/race"}
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

# --- Гусиная гонка ----------------------------------------------------------
# Ручка отдаёт {"status": "ok"|"attention"|"disabled", "problems": [...]}: коды
# без названий тенантов и чисел. Джобы гонки ловят все исключения и выходят с
# кодом 0, OnFailure у юнитов нет — без этой проверки сломавшуюся выгрузку
# заметили бы только по «обновлено N часов назад» на доске. Триггер — по
# СМЕНЕ набора проблем, как у HR.
race_text() {
  local out=""
  for code in $(echo "$1" | tr ',' ' '); do
    case "$code" in
      activation_overdue) out+="конкурс запланирован, старт наступил, а он не активен (тик 00:40 не сработал — journalctl -u signaris-hub-race-sync, race.activate_blocked_by_active); " ;;
      pull_stale) out+="успешной выгрузки iiko не было больше 2 часов (journalctl -u signaris-hub-race-sync: busy_skip / pull_failed); " ;;
      pull_error) out+="последняя выгрузка iiko упала (текст ошибки — в админке «Гонка» → «Выгрузка iiko»); " ;;
      close_stale) out+="ночное закрытие 03:45 не прошло или прошло без выгрузки iiko (journalctl -u signaris-hub-race-close: pull_failed / close_deferred); снимки и итоги догонит первое закрытие с выгрузкой; " ;;
      baseline_preliminary) out+="база активного конкурса осталась предварительной — пересчёт ночью не удался (кнопка «Пересчитать из iiko» в админке или следующий тик после 04:40); " ;;
      *) out+="$code; " ;;
    esac
  done
  echo "$out"
}

for url in $RACE_URLS; do
  state_file="$STATE_DIR/race.$(slug "$url").state"
  prev=$(cat "$state_file" 2>/dev/null || echo "")
  body=$(curl -fs --max-time 10 "$url" 2>/dev/null || echo "")
  # Недоступность самой ручки ловит проверка /api/env выше.
  [[ -n "$body" ]] || continue
  problems=$(echo "$body" | sed -n 's/.*"problems":[[:space:]]*\[\([^]]*\)\].*/\1/p' | tr -d '" ')
  [[ "$problems" == "$prev" ]] && continue
  echo "$problems" > "$state_file"
  if [[ -z "$problems" ]]; then
    logger -t signaris-hub-health "RACE RECOVERED $url"
    send_telegram "✅ [Hub] гонка: выгрузка iiko и закрытие снова в порядке: $url"
  else
    logger -t signaris-hub-health "RACE ATTENTION $url ($problems)"
    send_telegram "🔴 [Hub] Гусиная гонка: $(race_text "$problems")— $url"
  fi
done

# ─── Конвейер видео (0066): GET /api/health/media ──────────────────────────
#
# `disabled` — env-рубильник выключен (прод до go-live), проверять нечего.
# `attention` несёт коды (`ffmpeg_missing`, `stt_unconfigured`, `queue_stale`,
# `lease_expired`, `failed_burst`, `hedra_key_missing`, `hedra_auth`).
# Сообщение — когда тот же НАБОР кодов держится два прогона подряд (деплой с
# рестартом воркера длится секунды), восстановление — сразу и только если о
# сбое писали. Дефолт под `set -u` — ЯВНЫЙ.
MEDIA_URLS=${HEALTHCHECK_MEDIA_URLS:-"https://hub.signaris.ru/api/health/media https://hub-staging.signaris.ru/api/health/media"}

for url in $MEDIA_URLS; do
  media_key=$(echo "$url" | sed -E 's#https?://##; s#[^A-Za-z0-9._-]+#_#g')
  media_state="$STATE_DIR/media.$media_key.state"
  media_alerted="$STATE_DIR/media.$media_key.alerted"
  media_prev=$(cat "$media_state" 2>/dev/null || echo "|0")
  media_prev_problem=${media_prev%|*}
  media_prev_count=${media_prev##*|}
  media_body=$(curl -s --max-time 15 "$url" 2>/dev/null || true)
  media_status=$(echo "$media_body" | sed -n 's/.*"status":[[:space:]]*"\([a-z]*\)".*/\1/p' || true)
  case "$media_status" in
    ok|disabled) media_problem="" ;;
    attention)
      media_problem=$(echo "$media_body" | sed -n 's/.*"problems":[[:space:]]*\[\([^]]*\)\].*/\1/p' \
        | tr -d '" ' | tr ',' '+')
      [[ -n "$media_problem" ]] || media_problem="attention" ;;
    # Старый код без ручки (404 на проде до go-live) — не сбой.
    "") media_problem=$(echo "$media_body" | grep -q "Not Found" && echo "" || echo "unreachable") ;;
    *) media_problem="unreachable" ;;
  esac
  if [[ -z "$media_problem" ]]; then
    if [[ -f "$media_alerted" ]]; then
      logger -t signaris-hub-health "MEDIA RECOVERED $url"
      send_telegram "✅ [Hub] конвейер видео снова в порядке: $url"
      rm -f "$media_alerted"
    fi
    echo "|0" > "$media_state"
  else
    if [[ "$media_problem" == "$media_prev_problem" ]]; then
      media_count=$((media_prev_count + 1))
    else
      media_count=1
    fi
    echo "$media_problem|$media_count" > "$media_state"
    logger -t signaris-hub-health "MEDIA ATTENTION $url $media_problem (consecutive=$media_count)"
    if [[ "$media_count" -eq 2 ]]; then
      send_telegram "🔴 [Hub] конвейер видео: $media_problem — $url (journalctl -u signaris-hub*-media)"
      touch "$media_alerted"
    fi
  fi
done

# --- Распознавание речи (STT) ------------------------------------------------
# Юнит слушает только 127.0.0.1, поэтому опрос — прямо на хосте, а не через
# публичный адрес; проверяется только включённый юнит (на staging он выключен
# навсегда). До 22.10 этой проверки не было, и STT шесть недель висел, не
# отвечая даже на /health (docs/tech-debt/incidents.md).
#
# /health отвечает 200 `ready`, 503 `loading` | `missing` | `error`. Сообщение
# уходит, когда тот же набор держится ДВА прогона подряд (10 минут): рестарт
# при деплое длится секунды и будить не должен. Восстановление — сразу.
STT_UNIT=${HEALTHCHECK_STT_UNIT:-signaris-hub-stt.service}
STT_HEALTH_URL=${HEALTHCHECK_STT_URL:-http://127.0.0.1:5071/health}

stt_text() {
  case "$1" in
    unreachable) echo "сервис не отвечает (systemctl status ${STT_UNIT})" ;;
    loading) echo "модель грузится дольше обычного (journalctl -u ${STT_UNIT})" ;;
    missing) echo "модели нет в кэше — скачать: python -m app.jobs.stt_fetch_model (docs/DEPLOY.md)" ;;
    error) echo "модель не загрузилась (journalctl -u ${STT_UNIT}: stt.model_failed)" ;;
    *) echo "$1" ;;
  esac
}

if systemctl is-enabled --quiet "$STT_UNIT" 2>/dev/null; then
  stt_state="$STATE_DIR/stt.health.state"
  # Строка состояния: «проблема|сколько прогонов подряд».
  stt_prev=$(cat "$stt_state" 2>/dev/null || echo "|0")
  stt_prev_problem=${stt_prev%|*}
  stt_prev_count=${stt_prev##*|}
  # Без -f: при 503 нужен ответ, а не код возврата.
  stt_body=$(curl -s --max-time 10 "$STT_HEALTH_URL" 2>/dev/null || true)
  stt_status=$(echo "$stt_body" | sed -n 's/.*"status":[[:space:]]*"\([a-z]*\)".*/\1/p' || true)
  case "$stt_status" in
    ready|disabled) stt_problem="" ;;
    loading|missing|error) stt_problem="$stt_status" ;;
    *) stt_problem="unreachable" ;;
  esac
  # Метка «сообщение о сбое ушло»: о восстановлении пишем, только если
  # писали о сбое, — даже если проблема по дороге сменилась.
  stt_alerted="$STATE_DIR/stt.health.alerted"
  if [[ -z "$stt_problem" ]]; then
    if [[ -f "$stt_alerted" ]]; then
      logger -t signaris-hub-health "STT RECOVERED"
      send_telegram "✅ [Hub] распознавание речи снова работает"
      rm -f "$stt_alerted"
    fi
    echo "|0" > "$stt_state"
  else
    if [[ "$stt_problem" == "$stt_prev_problem" ]]; then
      stt_count=$((stt_prev_count + 1))
    else
      stt_count=1
    fi
    echo "$stt_problem|$stt_count" > "$stt_state"
    logger -t signaris-hub-health "STT ATTENTION $stt_problem (consecutive=$stt_count)"
    if [[ "$stt_count" -eq 2 ]]; then
      send_telegram "🔴 [Hub] распознавание речи: $(stt_text "$stt_problem")"
      touch "$stt_alerted"
    fi
  fi

  # Перезапуски сторожем или OOM-killer'ом: к следующему опросу юнит снова
  # здоров, и без этой проверки сбой прошёл бы молча. Журнал читается с
  # курсора прошлого прогона; первый прогон — за последние 6 минут. Счётчик
  # NRestarts не годится: его обнуляет любой ручной рестарт, в том числе
  # деплой. «Scheduled restart job» systemd пишет только при автоматическом
  # перезапуске (Restart=), причину — строкой «Failed with result '…'».
  stt_log=$(journalctl -u "$STT_UNIT" --cursor-file="$STATE_DIR/stt.journal.cursor" \
    --since "-6 min" -o cat --no-pager 2>/dev/null || true)
  stt_restarts=$(printf '%s\n' "$stt_log" | grep -c 'Scheduled restart job' || true)
  if [[ "${stt_restarts:-0}" -gt 0 ]]; then
    stt_reasons=$(printf '%s\n' "$stt_log" \
      | sed -n "s/.*Failed with result '\([a-z-]*\)'.*/\1/p" | sort -u | tr '\n' ' ' || true)
    stt_reasons=${stt_reasons% }
    logger -t signaris-hub-health "STT RESTARTED ${stt_restarts} (${stt_reasons:-?})"
    send_telegram "🔴 [Hub] распознавание речи перезапускалось: ${stt_restarts} раз(а), причина: ${stt_reasons:-не записана} — journalctl -u ${STT_UNIT}"
  fi
fi
