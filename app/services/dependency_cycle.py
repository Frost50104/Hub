"""Cycle detection for task dependencies (Phase 4.3).

Adding `predecessor → successor` is rejected if it would create a cycle
through existing edges. A cycle means `successor` is already reachable from
`predecessor` through some chain.

Implementation: BFS from `successor` along outgoing edges; if we hit
`predecessor`, adding the new edge would close a loop.

Runs in app code rather than via a recursive CTE because the graph is
small per project (≤ thousands of tasks) and the BFS is `O(V+E)` with
short-circuit on first hit — no measurable overhead compared to a CTE
round-trip.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import TaskDependency


async def would_create_cycle(
    session: AsyncSession,
    *,
    predecessor_id: UUID,
    successor_id: UUID,
) -> bool:
    """True if adding (predecessor → successor) would close a cycle."""
    if predecessor_id == successor_id:
        return True

    # BFS from `successor` following outgoing edges. If we land on
    # `predecessor` at any depth, the new edge would close a cycle.
    frontier: set[UUID] = {successor_id}
    visited: set[UUID] = set()

    while frontier:
        rows = await session.execute(
            select(TaskDependency.successor_id).where(
                TaskDependency.predecessor_id.in_(frontier)
            )
        )
        next_frontier: set[UUID] = set()
        for (next_id,) in rows.all():
            if next_id == predecessor_id:
                return True
            if next_id not in visited:
                next_frontier.add(next_id)
        visited.update(frontier)
        frontier = next_frontier - visited
    return False
