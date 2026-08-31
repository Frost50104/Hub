#!/usr/bin/env bash
# Retention sweep:
#   daily/   — дампы БД, 14 дней ПО MTIME
#   weekly/  — дампы БД, 42 дня ПО MTIME
#   files/   — снапшоты вложений, 14 штук ПО ИМЕНИ (см. ниже)
#   secrets/ — архивы ключей (backup-secrets.sh), 14 штук по имени
#
# ─── Почему снапшоты чистятся по ИМЕНИ, а не по -mtime (31.08) ──────────────
# `rsync -a` в backup-files.sh переносит на каталог снапшота mtime ИСХОДНОГО
# каталога, а не время съёмки. Замер 31.08: у сегодняшнего снапшота стояло
# 2026-07-22 — ровно mtime /opt/signaris-hub/attachments, — и `find -mtime +14`
# находил ВСЕ 46 снапшотов, включая свежий и тот, на который смотрит `latest`.
# Два месяца это не стреляло только потому, что юнит бежал от postgres и не имел
# прав на удаление; починка одних прав уничтожила бы файловые бэкапы на первом
# же прогоне. Имя каталога — дата съёмки, лексикографический порядок совпадает
# с хронологическим, и метаданные ФС в решение не входят вовсе.
#
# У дампов БД mtime НАСТОЯЩИЙ (их пишет gzip-редирект), поэтому их ветка
# осталась на -mtime. Не «унифицировать» её со снапшотами.
#
# ─── Почему нет `|| true` и подавления stderr ───────────────────────────────
# Юнит бежит от ROOT (чистить приходится за двумя владельцами: дампы
# postgres:postgres, снапшоты signaris:signaris под root:root каталогом).
# Раньше здесь стояло `-exec rm -rf {} + 2>/dev/null || true`, и отказ по правам
# два месяца печатал «cleanup ok». Sweep, который не смог удалить, обязан падать.
#
# DRY_RUN=1 — только показать, что удалилось бы.
set -euo pipefail

BACKUP_ROOT="/opt/signaris-hub/backups"
KEEP_SNAPSHOTS=14
KEEP_SECRETS=14
DRY_RUN="${DRY_RUN:-0}"

# Гард: скрипт root'овый и делает `rm -rf` по пути из переменной. Опечатка в
# BACKUP_ROOT стоит слишком дорого, чтобы полагаться на внимательность.
if [[ "$BACKUP_ROOT" != /opt/signaris-hub/backups ]]; then
  echo "отказ: BACKUP_ROOT='$BACKUP_ROOT' вне ожидаемого места" >&2
  exit 1
fi

PRUNED=0

# prune_by_name <каталог> <маска> <тип find> <сколько оставить> [защищённый путь]
#
# Оставляет `keep` новейших по имени, остальное удаляет. `protect` — путь,
# который нельзя трогать ни при каких условиях (цель симлинка `latest`):
# удалив его, мы бы не получили ошибки, а тихо выключили дедупликацию —
# `backup-files.sh` проверяет `[[ -d "$LATEST" ]]`, для битого симлинка это
# ложь, и следующий прогон ушёл бы в полный rsync без --link-dest.
prune_by_name() {
  local dir="$1" pattern="$2" ftype="$3" keep="$4" protect="${5:-}"
  local victim
  PRUNED=0
  [[ -d "$dir" ]] || return 0
  while IFS= read -r victim; do
    [[ -n "$victim" ]] || continue
    if [[ -n "$protect" && "$victim" == "$protect" ]]; then
      echo "пропускаю $victim — на него смотрит latest" >&2
      continue
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "  [dry-run] удалил бы $victim"
    else
      rm -rf -- "$victim"
    fi
    PRUNED=$((PRUNED + 1))
  done < <(
    find "$dir" -mindepth 1 -maxdepth 1 -name "$pattern" -type "$ftype" -print |
      sort | head -n "-$keep"
  )
}

# ─── Дампы БД: mtime настоящий ──────────────────────────────────────────────
if [[ -d "$BACKUP_ROOT/daily" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    find "$BACKUP_ROOT/daily" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +14 \
      -printf '  [dry-run] удалил бы %p\n'
  else
    find "$BACKUP_ROOT/daily" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +14 -delete
  fi
fi
if [[ -d "$BACKUP_ROOT/weekly" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    find "$BACKUP_ROOT/weekly" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +42 \
      -printf '  [dry-run] удалил бы %p\n'
  else
    find "$BACKUP_ROOT/weekly" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +42 -delete
  fi
fi

# ─── Снапшоты вложений: по имени, с защитой latest ──────────────────────────
if [[ -d "$BACKUP_ROOT/files" ]]; then
  for env_dir in "$BACKUP_ROOT/files"/*; do
    [[ -d "$env_dir" ]] || continue
    protect=""
    [[ -L "$env_dir/latest" ]] && protect="$(readlink -f "$env_dir/latest" || true)"
    prune_by_name "$env_dir" '20*' d "$KEEP_SNAPSHOTS" "$protect"
    echo "снапшотов удалено в $(basename "$env_dir"): $PRUNED"
  done
fi

# ─── Архивы ключей ──────────────────────────────────────────────────────────
prune_by_name "$BACKUP_ROOT/secrets" 'secrets-*.tar.gz.gpg' f "$KEEP_SECRETS"
echo "архивов ключей удалено: $PRUNED"

echo "cleanup ok"
