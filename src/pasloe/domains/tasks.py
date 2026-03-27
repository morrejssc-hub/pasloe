from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ForeignKey, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import get_session
from ..models import EventRecord
from . import EventDetailBase, EventDomain


TERMINAL_TASK_STATES = ("completed", "failed", "partial", "cancelled", "eval_failed")


class TaskDetail(EventDetailBase):
    __tablename__ = "detail_tasks"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    goal: Mapped[str | None] = mapped_column(String, nullable=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    @classmethod
    def from_event(cls, event_id: str, event_type: str, data: dict[str, Any]) -> "TaskDetail":
        state = event_type.rsplit(".", 1)[-1]
        return cls(
            event_id=event_id,
            task_id=str(data.get("task_id", "") or ""),
            parent_id=data.get("parent_task_id") or None,
            goal=data.get("goal") or None,
            team=data.get("team") or None,
            state=state,
            reason=data.get("reason") or None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "state": self.state,
            "team": self.team,
        }
        if self.parent_id:
            payload["parent_task_id"] = self.parent_id
        if self.goal:
            payload["goal"] = self.goal
        if self.reason:
            payload["reason"] = self.reason
        return payload


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_task_events(
    task_id: str | None = None,
    state: str | None = None,
    team: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    query = (
        select(TaskDetail, EventRecord)
        .join(EventRecord, EventRecord.id == TaskDetail.event_id)
        .order_by(EventRecord.ts.desc(), EventRecord.id.desc())
        .limit(limit)
    )
    if task_id:
        query = query.where(TaskDetail.task_id == task_id)
    if state:
        query = query.where(TaskDetail.state == state)
    if team:
        query = query.where(TaskDetail.team == team)
    if since:
        query = query.where(EventRecord.ts >= since)
    if until:
        query = query.where(EventRecord.ts <= until)
    rows = (await db.execute(query)).all()
    return [
        {
            "event_id": str(event.id),
            "event_type": event.type,
            "source_id": event.source_id,
            "ts": event.ts.isoformat(),
            **detail.to_payload(),
        }
        for detail, event in rows
    ]


@router.get("/stats")
async def task_stats(
    since: datetime | None = None,
    team: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from_clause = TaskDetail
    filters = []
    if since is not None:
        from_clause = TaskDetail.__table__.join(EventRecord.__table__, EventRecord.id == TaskDetail.event_id)
        filters.append(EventRecord.ts >= since)
    if team:
        filters.append(TaskDetail.team == team)

    event_counts_by_state = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(TaskDetail.state, func.count())
                .select_from(from_clause)
                .where(*filters)
                .group_by(TaskDetail.state)
            )
        ).all()
    }

    created_ids = {
        row[0]
        for row in (
            await db.execute(
                select(TaskDetail.task_id)
                .select_from(from_clause)
                .where(*filters)
                .distinct()
            )
        ).all()
    }
    terminal_ids = {
        row[0]
        for row in (
            await db.execute(
                select(TaskDetail.task_id)
                .select_from(from_clause)
                .where(*filters, TaskDetail.state.in_(TERMINAL_TASK_STATES))
                .distinct()
            )
        ).all()
    }

    return {
        "event_counts_by_state": event_counts_by_state,
        "active_task_count": len(created_ids - terminal_ids),
        "terminal_task_count": len(terminal_ids),
    }


domain = EventDomain(
    model_name="task",
    event_types=[
        "supervisor.task.created",
        "supervisor.task.evaluating",
        "supervisor.task.completed",
        "supervisor.task.failed",
        "supervisor.task.partial",
        "supervisor.task.eval_failed",
        "supervisor.task.cancelled",
    ],
    detail_model=TaskDetail,
    router=router,
)
