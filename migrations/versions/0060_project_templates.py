"""0060: шаблоны проектов — колонки и «замок» на уровне RLS.

Шаблон — это обычный проект с `is_template = true`, но НЕВИДИМЫЙ для всего
кода по умолчанию. Прятать его точечными фильтрами пришлось бы в ~25 выборках
без общей точки (списки, поиск, «Мои задачи», статистика, ассистент, cron под
bypass), поэтому шаблон прячет сама политика RLS: к прежнему условию
«свой тенант ИЛИ bypass» добавлено «не шаблон ИЛИ область шаблона открыта».

Область — GUC `app.template_scope`, ставится `app/db.py::_apply_rls_on_begin`
на КАЖДОЙ транзакции (урок 01.08: грязное соединение пула):
  ''            — закрыто (по умолчанию; NULL до первой установки — тоже);
  'all'         — все шаблоны тенанта (только библиотека);
  '<uuid>'      — один шаблон (его страница и копирование).
Замок действует И под bypass_rls: cron-джобы шаблоны не видят.

Дочерние таблицы (колонки, метки, исполнители, вложения…) НЕ запираются:
каждая их кросс-проектная выборка идёт через JOIN на tasks/projects, а
подписанная отдача вложений читает task_attachments под bypass.

Ключ проекта: шаблоны выходят из пространства ключей (частичный UNIQUE
`WHERE NOT is_template`) — иначе `generate_unique_key`, не видящий шаблонов
под RLS, упирался бы в их ключи на создании проекта и личного пространства.

Функции — первые в этой БД. Владелец — роль миграций (на проде SUPERUSER),
поэтому RLS внутри они обходят сами; `search_path` зафиксирован.

`downgrade` отказывается работать, пока в БД есть шаблоны: откат снял бы
замок, и все шаблоны разом всплыли бы в живых списках.

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels = None
depends_on = None

_BASE = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)
_SCOPE = "current_setting('app.template_scope', true)"

# Скобки вокруг прежнего `A OR B` обязательны: без них получилось бы
# `A OR (B AND lock)`, и для обычной тенантной сессии замок бы не действовал.
PROJECTS_POLICY = (
    f"({_BASE}) AND (NOT is_template OR {_SCOPE} = 'all' OR {_SCOPE} = id::text)"
)
TASKS_POLICY = (
    f"({_BASE}) AND (NOT is_template OR {_SCOPE} = 'all' "
    f"OR {_SCOPE} = project_id::text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column(
        "projects",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("projects", sa.Column("template_anchor_on", sa.Date(), nullable=True))
    # Без внешнего ключа намеренно: `ON DELETE SET NULL` при удалении шаблона
    # брал бы блокировки строк всех проектов, созданных из него, и спорил бы с
    # `allocate_task_seq` (UPDATE строки проекта) при создании задач в них.
    op.add_column(
        "projects",
        sa.Column("created_from_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Снимок имени: под замком живой проект имя шаблона прочитать не может.
    op.add_column(
        "projects", sa.Column("created_from_template_name", sa.String(255), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tasks",
        sa.Column("template_copy", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_check_constraint(
        "ck_projects_template_not_personal",
        "projects",
        "NOT (is_template AND personal_owner_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_projects_template_no_folder",
        "projects",
        "NOT (is_template AND folder_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_projects_template_anchor",
        "projects",
        "template_anchor_on IS NULL OR is_template",
    )

    op.drop_constraint("uq_projects_tenant_key", "projects", type_="unique")
    op.create_index(
        "uq_projects_tenant_key",
        "projects",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("NOT is_template"),
    )
    op.create_index(
        "ix_projects_templates",
        "projects",
        ["tenant_id"],
        postgresql_where=sa.text("is_template"),
    )
    op.create_index(
        "ix_projects_created_from_template",
        "projects",
        ["created_from_template_id"],
        postgresql_where=sa.text("created_from_template_id IS NOT NULL"),
    )

    op.execute(f"ALTER POLICY projects_rls ON projects USING ({PROJECTS_POLICY})")
    op.execute(f"ALTER POLICY tasks_rls ON tasks USING ({TASKS_POLICY})")

    # Флаг задачи обязан совпадать с проектом, подзадача — стоять по ту же
    # сторону замка, что родитель. SECURITY DEFINER: под RLS вызывающего
    # закрытый шаблон невидим, и триггер принял бы NULL за «живой проект» —
    # задача с is_template=false пролезла бы в шаблон видимой всем. По той же
    # причине NULL (проект не найден при живом FK = владелец потерял обход
    # RLS) — тоже отказ, а не пропуск. RAISE, а не тихая подмена флага: ORM
    # держал бы старое значение, и заглушка уведомлений прочла бы False.
    op.execute(
        """
        CREATE FUNCTION tasks_template_guard() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
          proj_tpl boolean;
          parent_tpl boolean;
        BEGIN
          SELECT p.is_template INTO proj_tpl FROM projects p WHERE p.id = NEW.project_id;
          IF proj_tpl IS NULL THEN
            RAISE EXCEPTION 'tasks_template_guard: проект % не найден', NEW.project_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.is_template IS DISTINCT FROM proj_tpl THEN
            RAISE EXCEPTION 'tasks.is_template не совпадает с проектом'
              USING ERRCODE = 'check_violation',
                    CONSTRAINT = 'ck_tasks_is_template_matches_project';
          END IF;
          IF NEW.parent_task_id IS NOT NULL THEN
            SELECT t.is_template INTO parent_tpl FROM tasks t WHERE t.id = NEW.parent_task_id;
            IF parent_tpl IS DISTINCT FROM NEW.is_template THEN
              RAISE EXCEPTION 'подзадача и родитель по разные стороны шаблона'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tasks_parent_template_parity';
            END IF;
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_tasks_template_guard "
        "BEFORE INSERT OR UPDATE OF project_id, is_template, parent_task_id ON tasks "
        "FOR EACH ROW EXECUTE FUNCTION tasks_template_guard()"
    )

    # Проект нельзя превратить в шаблон или обратно — только скопировать.
    op.execute(
        """
        CREATE FUNCTION projects_is_template_immutable() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          RAISE EXCEPTION 'projects.is_template неизменяем'
            USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_projects_is_template_immutable "
        "BEFORE UPDATE OF is_template ON projects FOR EACH ROW "
        "WHEN (OLD.is_template IS DISTINCT FROM NEW.is_template) "
        "EXECUTE FUNCTION projects_is_template_immutable()"
    )

    # Зонд для резолвера: «этот проект/задача — шаблон моего тенанта? чей?»
    # Права проверяются ДО того, как строки шаблона попадут в сессию. Фильтр
    # тенанта внутри обязателен: RLS в SECURITY DEFINER не действует. Под
    # bypass `app.tenant_id` пуст — джобы подглядеть не смогут.
    op.execute(
        """
        CREATE FUNCTION app_template_lookup(p_project_id uuid, p_task_id uuid)
        RETURNS TABLE (project_id uuid, created_by uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
          SELECT p.id, p.created_by
          FROM projects p
          WHERE p.is_template
            AND p.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND p.id = COALESCE(
                  p_project_id,
                  (SELECT t.project_id FROM tasks t
                   WHERE t.id = p_task_id AND t.is_template))
        $$
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
          SET LOCAL app.bypass_rls = 'on';
          SET LOCAL app.template_scope = 'all';
          IF EXISTS (SELECT 1 FROM projects WHERE is_template) THEN
            RAISE EXCEPTION
              'В БД есть шаблоны проектов: откат 0060 открыл бы их всем. '
              'Сначала удалите шаблоны (DELETE /api/projects/{id}), потом повторите.';
          END IF;
        END
        $$
        """
    )
    op.execute("DROP FUNCTION app_template_lookup(uuid, uuid)")
    op.execute("DROP TRIGGER trg_projects_is_template_immutable ON projects")
    op.execute("DROP FUNCTION projects_is_template_immutable()")
    op.execute("DROP TRIGGER trg_tasks_template_guard ON tasks")
    op.execute("DROP FUNCTION tasks_template_guard()")

    op.execute(f"ALTER POLICY tasks_rls ON tasks USING ({_BASE})")
    op.execute(f"ALTER POLICY projects_rls ON projects USING ({_BASE})")

    op.drop_index("ix_projects_created_from_template", table_name="projects")
    op.drop_index("ix_projects_templates", table_name="projects")
    op.drop_index("uq_projects_tenant_key", table_name="projects")
    op.create_unique_constraint("uq_projects_tenant_key", "projects", ["tenant_id", "key"])

    op.drop_constraint("ck_projects_template_anchor", "projects", type_="check")
    op.drop_constraint("ck_projects_template_no_folder", "projects", type_="check")
    op.drop_constraint("ck_projects_template_not_personal", "projects", type_="check")

    op.drop_column("tasks", "template_copy")
    op.drop_column("tasks", "is_template")
    op.drop_column("projects", "created_from_template_name")
    op.drop_column("projects", "created_from_template_id")
    op.drop_column("projects", "template_anchor_on")
    op.drop_column("projects", "is_template")
