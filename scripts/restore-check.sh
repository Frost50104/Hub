#!/usr/bin/env bash
# Репетиция восстановления: развернуть дамп во ВРЕМЕННУЮ базу, проверить и снести.
#
# Бэкап, из которого ни разу не разворачивались, — гипотеза. Здесь она
# проверяется целиком: файл читается, схема соответствует текущей миграции,
# данные на месте.
#
# Дамп нельзя скормить pg_restore напрямую — это `pg_dump -Fc`, поверх которого
# ещё раз `gzip -9`, и pg_restore отвечает «input file does not appear to be a
# valid archive». Только через `gunzip -c |`.
#
#   ./restore-check.sh /opt/signaris-hub/backups/daily/db-signaris_hub_db-2026-08-31.sql.gz
set -euo pipefail

DUMP="${1:?usage: $0 <dump.sql.gz>}"
LIVE_DB="${LIVE_DB:-signaris_hub_db}"
[[ -f "$DUMP" ]] || { echo "нет файла: $DUMP" >&2; exit 1; }

# Имя собирается ТОЛЬКО из литерала и метки времени: снаружи в него ничего не
# попадает, потому что дальше по этому имени идёт DROP DATABASE.
DB="restore_check_$(date +%Y%m%d%H%M%S)"

psql_live() { sudo -u postgres psql -tAX -d "$LIVE_DB" -c "$1"; }
psql_tmp()  { sudo -u postgres psql -tAX -d "$DB" -c "$1"; }

cleanup() {
  echo "--- сношу временную базу $DB"
  sudo -u postgres dropdb --if-exists "$DB"
}
trap cleanup EXIT

echo "=== восстанавливаю $DUMP → $DB"
sudo -u postgres createdb "$DB"
# --no-owner/--no-acl: временная база не должна зависеть от того, совпали ли
# роли. Политики RLS при этом восстанавливаются и проверяются ниже.
gunzip -c "$DUMP" | sudo -u postgres pg_restore --no-owner --no-acl -d "$DB" 2>/tmp/restore-check.err || true
ERRORS=$(grep -c '^pg_restore: error' /tmp/restore-check.err || true)
echo "ошибок pg_restore: $ERRORS"
[[ "$ERRORS" == "0" ]] || { sed -n 1,10p /tmp/restore-check.err; exit 1; }

echo "=== схема"
HEAD_LIVE=$(psql_live "SELECT version_num FROM alembic_version;")
HEAD_TMP=$(psql_tmp  "SELECT version_num FROM alembic_version;")
echo "alembic: в дампе $HEAD_TMP, на живой базе $HEAD_LIVE"
# Дамп «полный, но от старой схемы» иначе выглядит совершенно здоровым.
[[ "$HEAD_TMP" == "$HEAD_LIVE" ]] || { echo "РАСХОЖДЕНИЕ МИГРАЦИЙ" >&2; exit 1; }

echo "=== данные (в дампе / на живой базе)"
FAILED=0
for t in projects tasks employee_profiles task_comments; do
  N_TMP=$(psql_tmp  "SELECT count(*) FROM $t;")
  N_LIVE=$(psql_live "SELECT count(*) FROM $t;")
  printf '  %-20s %8s / %8s\n' "$t" "$N_TMP" "$N_LIVE"
  [[ "$N_TMP" -gt 0 ]] || { echo "  ПУСТО: $t" >&2; FAILED=1; }
done

# RLS — не косметика: политики восстанавливаются отдельно от таблиц, и дамп без
# них выглядит рабочим ровно до первого кросс-tenant запроса.
POL=$(psql_tmp "SELECT count(*) FROM pg_policies WHERE schemaname='public';")
echo "  RLS-политик         $POL"
[[ "$POL" -gt 0 ]] || { echo "  НЕТ RLS-ПОЛИТИК" >&2; FAILED=1; }

[[ "$FAILED" == "0" ]] || exit 1
echo "=== restore-check ok"
