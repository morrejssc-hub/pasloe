from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Boolean, ForeignKey, Integer, String, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import get_session
from ..models import EventRecord
from . import EventDetailBase, EventDomain


class ToolDetail(EventDetailBase):
    __tablename__ = "detail_tools"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @classmethod
    def from_event(cls, event_id: str, event_type: str, data: dict[str, Any]) -> "ToolDetail":
        state = event_type.rsplit(".", 1)[-1]
        return cls(
            event_id=event_id,
            job_id=data.get("job_id") or None,
            task_id=data.get("task_id") or None,
            tool_name=data.get("tool_name") or None,
            tool_call_id=data.get("tool_call_id") or None,
            state=state,
            success=data.get("success"),
            duration_ms=data.get("duration_ms"),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = {"state": self.state}
        for key in ("job_id", "task_id", "tool_name", "tool_call_id", "success", "duration_ms"):
            value = getattr(self, key)
            if value is not None and value != "":
                payload[key] = value
        return payload


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tool_events(
    job_id: str | None = None,
    tool_name: str | None = None,
    state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    query = (
        select(ToolDetail, EventRecord)
        .join(EventRecord, EventRecord.id == ToolDetail.event_id)
        .order_by(EventRecord.ts.desc(), EventRecord.id.desc())
        .limit(limit)
    )
    if job_id:
        query = query.where(ToolDetail.job_id == job_id)
    if tool_name:
        query = query.where(ToolDetail.tool_name == tool_name)
    if state:
        query = query.where(ToolDetail.state == state)
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
async def tool_stats(
    since: datetime | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(
        ToolDetail.tool_name,
        func.count(),
        func.coalesce(func.sum(case((ToolDetail.success.is_(True), 1), else_=0)), 0),
    ).where(ToolDetail.state == "result")
    if since:
        query = query.join(EventRecord, EventRecord.id == ToolDetail.event_id).where(EventRecord.ts >= since)
    query = query.group_by(ToolDetail.tool_name)
    rows = (await db.execute(query)).all()
    by_tool = {
        row[0] or "unknown": {
            "results": row[1],
            "successes": row[2],
            "success_rate": (row[2] / row[1]) if row[1] else 0.0,
        }
        for row in rows
    }
    return {"by_tool": by_tool}


domain = EventDomain(
    model_name="tool",
    event_types=[
        "agent.tool.exec",
        "agent.tool.result",
    ],
    detail_model=ToolDetail,
    router=router,
)
