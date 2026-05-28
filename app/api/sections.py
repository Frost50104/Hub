"""Section CRUD — list/create scoped to /projects/{id}/sections;
update/delete addressed directly via /sections/{section_id}.

Position rules:
- New section without position: appended (max+1).
- New section with position N: shifts existing N..max up by 1.
- Update position: shifts other sections to make room. Uniqueness constraint
  is DEFERRABLE so the intermediate states are fine within one tx.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.section import Section
from app.schemas.section import SectionCreate, SectionResponse, SectionUpdate
from app.services.project_access import require_project_role

router = APIRouter(tags=["sections"])


@router.get("/projects/{project_id}/sections", response_model=list[SectionResponse])
async def list_sections(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[SectionResponse]:
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(Section).where(Section.project_id == project_id).order_by(Section.position)
    )
    return [SectionResponse.model_validate(s) for s in rows.scalars().all()]


@router.post(
    "/projects/{project_id}/sections",
    response_model=SectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    project_id: UUID,
    body: SectionCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SectionResponse:
    await require_project_role(db, project_id, principal, allow=("owner", "editor"))

    # Defer unique constraint for the whole tx so any shifting we do below
    # doesn't trip on intermediate duplicates.
    await db.execute(text("SET CONSTRAINTS uq_sections_project_position DEFERRED"))

    next_position = (
        await db.execute(
            select(func.coalesce(func.max(Section.position) + 1, 0)).where(
                Section.project_id == project_id
            )
        )
    ).scalar_one()
    target_position = next_position if body.position is None else body.position

    if body.position is not None and body.position < next_position:
        await db.execute(
            update(Section)
            .where(Section.project_id == project_id, Section.position >= body.position)
            .values(position=Section.position + 1)
        )

    section = Section(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        name=body.name,
        position=target_position,
    )
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return SectionResponse.model_validate(section)


@router.patch("/sections/{section_id}", response_model=SectionResponse)
async def update_section(
    section_id: UUID,
    body: SectionUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SectionResponse:
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Секция не найдена")
    await require_project_role(
        db, section.project_id, principal, allow=("owner", "editor")
    )

    if body.position is not None and body.position != section.position:
        await db.execute(text("SET CONSTRAINTS uq_sections_project_position DEFERRED"))
        old_pos = section.position
        new_pos = body.position
        if new_pos > old_pos:
            # Move others left.
            await db.execute(
                update(Section)
                .where(
                    Section.project_id == section.project_id,
                    Section.position > old_pos,
                    Section.position <= new_pos,
                    Section.id != section.id,
                )
                .values(position=Section.position - 1)
            )
        else:
            # Move others right.
            await db.execute(
                update(Section)
                .where(
                    Section.project_id == section.project_id,
                    Section.position >= new_pos,
                    Section.position < old_pos,
                    Section.id != section.id,
                )
                .values(position=Section.position + 1)
            )
        section.position = new_pos

    if body.name is not None:
        section.name = body.name

    await db.commit()
    await db.refresh(section)
    return SectionResponse.model_validate(section)


@router.delete("/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(
    section_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Секция не найдена")
    await require_project_role(
        db, section.project_id, principal, allow=("owner",)
    )
    await db.execute(text("SET CONSTRAINTS uq_sections_project_position DEFERRED"))
    deleted_position = section.position
    await db.delete(section)
    # Shift positions down to keep contiguous ordering.
    await db.execute(
        update(Section)
        .where(
            Section.project_id == section.project_id,
            Section.position > deleted_position,
        )
        .values(position=Section.position - 1)
    )
    await db.commit()
