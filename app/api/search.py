"""GET /api/search?q=... — full-text + DSL filters across projects + tasks.

Two response shapes:
- **Legacy** (no `group_by`): `{projects: SearchHit[], tasks: SearchHit[]}` —
  back-compat for the Sidebar quick-search dropdown. Caps 10/10.
- **Grouped** (`group_by=project`): `{groups: SearchGroup[], total: int}` —
  used by `/search` page. Tasks bucketed by project.

DSL parsing lives in `app.services.search_dsl`. Backend takes the parsed
filters and compiles a SQLAlchemy WHERE: text part hits
`tasks.search_vector` (GIN, ranked) + ILIKE fallback for short queries
(<3 chars where tsquery returns empty); filters use indexed columns.

Visibility:
- `hub:admin` sees every project in the tenant.
- Everyone else: only projects they're a member of (ProjectMember JOIN).

Rate-limited via `enforce_rate_limit(bucket="search")` — 60/min/user.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth_any
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskComment
from app.services.project_access import is_hub_admin
from app.services.public_token import initials
from app.services.search_dsl import ParsedQuery
from app.services.search_dsl import parse as parse_dsl

router = APIRouter(tags=["search"])

_LEGACY_LIMIT = 10
_GROUPED_LIMIT = 100
_MIN_FTS_LEN = 3  # below this tsquery often returns nothing useful → ILIKE


class SearchHit(BaseModel):
    kind: Literal["project", "task"]
    id: UUID
    title: str
    subtitle: str | None = None
    project_id: UUID | None = None


class SearchTaskHit(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str
    due_at: datetime | None
    assignee_id: UUID | None
    # `headline` is a snippet with the user's query highlighted via custom
    # marker pair ‹‹…››. Client splits on it — safer than serving HTML.
    headline: str | None = None


class SearchCommentHit(BaseModel):
    task_id: UUID
    task_title: str
    snippet: str  # ts_headline with ‹‹…›› markers
    author_initials: str | None
    created_at: datetime


class SearchGroup(BaseModel):
    project_id: UUID
    project_name: str
    project_key: str
    tasks: list[SearchTaskHit]
    comments: list[SearchCommentHit] = []


class SearchResponseLegacy(BaseModel):
    projects: list[SearchHit]
    tasks: list[SearchHit]


class SearchResponseGrouped(BaseModel):
    groups: list[SearchGroup]
    total: int
    parsed: dict


def _ilike_pattern(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _apply_dsl_filters(stmt, parsed: ParsedQuery, *, employee_id: UUID):
    """Append WHERE clauses from a ParsedQuery onto a tasks `select()`."""
    if parsed.assignee == "me":
        stmt = stmt.where(Task.assignee_id == employee_id)
    elif parsed.assignee is not None:
        try:
            stmt = stmt.where(Task.assignee_id == UUID(parsed.assignee))
        except ValueError:
            # DSL parser already filtered out malformed UUIDs, but be safe.
            pass
    if parsed.status is not None:
        stmt = stmt.where(Task.status == parsed.status)
    if parsed.priority is not None:
        stmt = stmt.where(Task.priority == parsed.priority)
    if parsed.due_date is not None:
        dt = datetime.combine(parsed.due_date, time(0, 0, 0), tzinfo=UTC)
        next_day = datetime.combine(parsed.due_date, time(23, 59, 59, 999_999), tzinfo=UTC)
        if parsed.due_op == "<":
            stmt = stmt.where(Task.due_at < dt)
        elif parsed.due_op == ">":
            stmt = stmt.where(Task.due_at > next_day)
        else:  # "="
            stmt = stmt.where(Task.due_at >= dt, Task.due_at <= next_day)
    if parsed.created_date is not None:
        dt = datetime.combine(parsed.created_date, time(0, 0, 0), tzinfo=UTC)
        next_day = datetime.combine(parsed.created_date, time(23, 59, 59, 999_999), tzinfo=UTC)
        if parsed.created_op == "<":
            stmt = stmt.where(Task.created_at < dt)
        elif parsed.created_op == ">":
            stmt = stmt.where(Task.created_at > next_day)
        else:
            stmt = stmt.where(Task.created_at >= dt, Task.created_at <= next_day)
    return stmt


def _apply_text(stmt, text_query: str):
    """Apply tsvector @@ websearch + trigram fallback for short queries."""
    if not text_query:
        return stmt
    if len(text_query) >= _MIN_FTS_LEN:
        # `websearch_to_tsquery` accepts quotes, OR, - operators naturally —
        # safer surface than `plainto_tsquery` for free user input.
        # Reflect the generated column via text() — SQLAlchemy doesn't model
        # `STORED GENERATED` columns gracefully. The bind param must be the
        # plain query STRING (an SQL function object is not bindable).
        return stmt.where(
            text(
                "tasks.search_vector @@ websearch_to_tsquery('russian', :tsq)"
            ).bindparams(tsq=text_query)
        )
    # Sub-3-char: tsquery returns ø → ILIKE fallback on title.
    return stmt.where(Task.title.ilike(_ilike_pattern(text_query)))


# Use distinctive markers so the client can split the snippet without
# rendering raw HTML (which would be a source of XSS for user-supplied
# titles/descriptions). The chars `‹›` don't appear in normal RU/EN text.
_HEADLINE_OPTIONS = (
    "StartSel=‹‹, StopSel=››, "
    "MinWords=10, MaxWords=24, ShortWord=2, HighlightAll=false"
)


def _headline_expr(source_col, text_query: str):
    """Build a `ts_headline(...)` expression for a column.

    Returns the source column unchanged if the query is below FTS minimum
    length — ts_headline on empty tsquery just returns the whole text.
    """
    if len(text_query) < _MIN_FTS_LEN:
        return source_col
    return func.ts_headline(
        "russian",
        source_col,
        func.websearch_to_tsquery("russian", text_query),
        _HEADLINE_OPTIONS,
    )


def _serialize_legacy_task(t: Task, project_name: str) -> SearchHit:
    return SearchHit(
        kind="task",
        id=t.id,
        title=t.title,
        subtitle=project_name,
        project_id=t.project_id,
    )


def _parsed_summary(parsed: ParsedQuery) -> dict:
    """Echo back what we extracted so the UI can show chips."""
    return {
        "text": parsed.text,
        "assignee": parsed.assignee,
        "status": parsed.status,
        "priority": parsed.priority,
        "due_op": parsed.due_op,
        "due_date": parsed.due_date.isoformat() if parsed.due_date else None,
        "created_op": parsed.created_op,
        "created_date": parsed.created_date.isoformat() if parsed.created_date else None,
    }


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2, max_length=256),
    group_by: Literal["project"] | None = Query(default=None),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> SearchResponseLegacy | SearchResponseGrouped:
    await enforce_rate_limit(
        bucket="search",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )

    parsed = parse_dsl(q)
    is_admin = is_hub_admin(principal)

    # ─── Task query ─────────────────────────────────────────────────────────
    # ts_headline runs on description so the user sees WHY a task matched.
    headline_col = _headline_expr(Task.description, parsed.text)

    task_stmt = (
        select(Task, Project.name, Project.key, headline_col.label("headline"))
        .join(Project, Project.id == Task.project_id)
        .where(Task.archived_at.is_(None), Project.archived_at.is_(None))
    )
    if not is_admin:
        task_stmt = task_stmt.join(
            ProjectMember, ProjectMember.project_id == Task.project_id
        ).where(ProjectMember.employee_id == principal.employee_id)

    task_stmt = _apply_dsl_filters(
        task_stmt, parsed, employee_id=principal.employee_id
    )
    task_stmt = _apply_text(task_stmt, parsed.text)
    task_stmt = task_stmt.order_by(Task.updated_at.desc())

    if group_by != "project":
        # ─── Legacy compact response (Sidebar quick-search) ─────────────────
        # Project ILIKE on the bare query (filters are tasks-only).
        project_stmt = select(Project).where(
            Project.archived_at.is_(None),
            Project.name.ilike(_ilike_pattern(parsed.text or q)),
        )
        if not is_admin:
            project_stmt = project_stmt.join(
                ProjectMember, ProjectMember.project_id == Project.id
            ).where(ProjectMember.employee_id == principal.employee_id)
        project_rows = (
            await db.execute(project_stmt.limit(_LEGACY_LIMIT))
        ).scalars().all()

        task_rows = (await db.execute(task_stmt.limit(_LEGACY_LIMIT))).all()
        return SearchResponseLegacy(
            projects=[
                SearchHit(kind="project", id=p.id, title=p.name, subtitle=p.key)
                for p in project_rows
            ],
            tasks=[
                _serialize_legacy_task(t, project_name)
                for t, project_name, _, _ in task_rows
            ],
        )

    # ─── Grouped response (advanced /search page) ───────────────────────────
    task_rows = (await db.execute(task_stmt.limit(_GROUPED_LIMIT))).all()
    by_project: dict[UUID, SearchGroup] = {}
    for t, project_name, project_key, headline in task_rows:
        bucket = by_project.get(t.project_id)
        if bucket is None:
            bucket = SearchGroup(
                project_id=t.project_id,
                project_name=project_name,
                project_key=project_key,
                tasks=[],
                comments=[],
            )
            by_project[t.project_id] = bucket
        bucket.tasks.append(
            SearchTaskHit(
                id=t.id,
                title=t.title,
                status=t.status,
                priority=t.priority,
                due_at=t.due_at,
                assignee_id=t.assignee_id,
                headline=headline if (headline and headline != t.description) else None,
            )
        )

    # ─── Comment query (only when there's a text part to match against). ───
    if parsed.text and len(parsed.text) >= _MIN_FTS_LEN:
        comment_snippet = _headline_expr(TaskComment.body, parsed.text)
        comment_stmt = (
            select(
                TaskComment.task_id,
                Task.title.label("task_title"),
                Task.project_id,
                Project.name.label("project_name"),
                Project.key.label("project_key"),
                comment_snippet.label("snippet"),
                ShadowUser.full_name,
                ShadowUser.email,
                TaskComment.created_at,
            )
            .join(Task, Task.id == TaskComment.task_id)
            .join(Project, Project.id == Task.project_id)
            .join(
                ShadowUser,
                (ShadowUser.employee_id == TaskComment.author_id)
                & (ShadowUser.deleted_at.is_(None)),
                isouter=True,
            )
            .where(
                TaskComment.deleted_at.is_(None),
                Task.archived_at.is_(None),
                Project.archived_at.is_(None),
                text(
                    "to_tsvector('russian', task_comments.body) @@ "
                    "websearch_to_tsquery('russian', :tsq)"
                ).bindparams(tsq=parsed.text),
            )
            .order_by(TaskComment.created_at.desc())
        )
        if not is_admin:
            comment_stmt = comment_stmt.join(
                ProjectMember, ProjectMember.project_id == Task.project_id
            ).where(ProjectMember.employee_id == principal.employee_id)
        comment_rows = (
            await db.execute(comment_stmt.limit(_GROUPED_LIMIT))
        ).all()

        for r in comment_rows:
            bucket = by_project.get(r.project_id)
            if bucket is None:
                # Show project groups that ONLY have comment matches too.
                # project_name/key come from the joined Project — no extra query.
                bucket = SearchGroup(
                    project_id=r.project_id,
                    project_name=r.project_name,
                    project_key=r.project_key,
                    tasks=[],
                    comments=[],
                )
                by_project[r.project_id] = bucket
            bucket.comments.append(
                SearchCommentHit(
                    task_id=r.task_id,
                    task_title=r.task_title,
                    snippet=r.snippet,
                    author_initials=initials(r.full_name, r.email),
                    created_at=r.created_at,
                )
            )

    groups = sorted(by_project.values(), key=lambda g: g.project_name.lower())
    return SearchResponseGrouped(
        groups=groups,
        total=sum(len(g.tasks) + len(g.comments) for g in groups),
        parsed=_parsed_summary(parsed),
    )
