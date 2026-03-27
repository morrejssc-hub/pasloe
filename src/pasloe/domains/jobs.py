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


TERMINAL_JOB_STATES = ("completed", "failed", "cancelled")


class JobDetail(EventDetailBase):
    __tablename__ = "detail_jobs"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    git_ref: Mapped[str | None] = mapped_column(String, nullable=True)

    @classmethod
    def from_event(cls, event_id: str, event_type: str, data: dict[str, Any]) -> "JobDetail":
        state = event_type.rsplit(".", 1)[-1]
        summary = data.get("summary") or data.get("error") or data.get("reason") or None
        return cls(
            event_id=event_id,
            job_id=str(data.get("job_id", "") or ""),
            task_id=data.get("task_id") or None,
            role=data.get("role") or None,
            team=data.get("team") or None,
            state=state,
            code=data.get("code") or None,
            summary=summary,
            git_ref=data.get("git_ref") or None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "job_id": self.job_id,
            "state": self.state,
        }
        for key in ("task_id", "role", "team", "code", "summary", "git_ref"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return payload


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_job_events(
    job_id: str | None = None,
    task_id: str | None = None,
    role: str | None = None,
    state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    query = (
        select(JobDetail, EventRecord)
        .join(EventRecord, EventRecord.id == JobDetail.event_id)
        .order_by(EventRecord.ts.desc(), EventRecord.id.desc())
        .limit(limit)
    )
    if job_id:
        query = query.where(JobDetail.job_id == job_id)
    if task_id:
        query = query.where(JobDetail.task_id == task_id)
    if role:
        query = query.where(JobDetail.role == role)
    if state:
        query = query.where(JobDetail.state == state)
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
async def job_stats(
    since: datetime | None = None,
    role: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from_clause = JobDetail
    filters = []
    if since is not None:
        from_clause = JobDetail.__table__.join(EventRecord.__table__, EventRecord.id == JobDetail.event_id)
        filters.append(EventRecord.ts >= since)
    if role:
        filters.append(JobDetail.role == role)

    events_by_state = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(JobDetail.state, func.count())
                .select_from(from_clause)
                .where(*filters)
                .group_by(JobDetail.state)
            )
        ).all()
    }
    jobs_seen = {
        row[0]
        for row in (
            await db.execute(
                select(JobDetail.job_id)
                .select_from(from_clause)
                .where(*filters)
                .distinct()
            )
        ).all()
    }
    terminal_jobs = {
        row[0]
        for row in (
            await db.execute(
                select(JobDetail.job_id)
                .select_from(from_clause)
                .where(*filters, JobDetail.state.in_(TERMINAL_JOB_STATES))
                .distinct()
            )
        ).all()
    }

    return {
        "event_counts_by_state": events_by_state,
        "active_job_count": len(jobs_seen - terminal_jobs),
        "terminal_job_count": len(terminal_jobs),
    }


domain = EventDomain(
    model_name="job",
    event_types=[
        "agent.job.started",
        "agent.job.completed",
        "agent.job.failed",
        "agent.job.cancelled",
        "agent.job.runtime_issue",
        "agent.job.stage_transition",
        "agent.job.spawn_request",
        "supervisor.job.enqueued",
        "supervisor.job.launched",
    ],
    detail_model=JobDetail,
    router=router,
)
