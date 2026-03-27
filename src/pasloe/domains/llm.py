from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ForeignKey, Float, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import get_session
from ..models import EventRecord
from . import EventDetailBase, EventDomain


_MODEL_PRICING_PER_MILLION: tuple[tuple[str, tuple[float, float]], ...] = (
    ("claude-sonnet-4-6", (3.0, 15.0)),
    ("claude-3-7-sonnet", (3.0, 15.0)),
    ("claude-3-5-sonnet", (3.0, 15.0)),
    ("gpt-5-mini", (0.25, 2.0)),
    ("gpt-5", (1.25, 10.0)),
    ("gpt-4.1-mini", (0.40, 1.60)),
    ("gpt-4.1", (2.0, 8.0)),
    ("gpt-4o-mini", (0.15, 0.60)),
    ("gpt-4o", (2.5, 10.0)),
)


def _estimate_cost(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
    normalized = (model or "").strip().lower().split("/", 1)[-1]
    for prefix, (input_rate, output_rate) in _MODEL_PRICING_PER_MILLION:
        if normalized.startswith(prefix):
            return ((input_tokens or 0) / 1_000_000.0) * input_rate + ((output_tokens or 0) / 1_000_000.0) * output_rate
    return None


class LLMDetail(EventDetailBase):
    __tablename__ = "detail_llm"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)

    @classmethod
    def from_event(cls, event_id: str, event_type: str, data: dict[str, Any]) -> "LLMDetail":
        state = event_type.rsplit(".", 1)[-1]
        model = data.get("model") or None
        input_tokens = data.get("input_tokens")
        output_tokens = data.get("output_tokens")
        return cls(
            event_id=event_id,
            job_id=data.get("job_id") or None,
            task_id=data.get("task_id") or None,
            model=model,
            state=state,
            iteration=data.get("iteration"),
            finish_reason=data.get("finish_reason") or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=data.get("duration_ms"),
            cost_estimate=_estimate_cost(model, input_tokens, output_tokens) if state == "response" else None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload = {"state": self.state}
        for key in (
            "job_id",
            "task_id",
            "model",
            "iteration",
            "finish_reason",
            "input_tokens",
            "output_tokens",
            "duration_ms",
            "cost_estimate",
        ):
            value = getattr(self, key)
            if value is not None and value != "":
                payload[key] = value
        return payload


router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("")
async def list_llm_events(
    job_id: str | None = None,
    model: str | None = None,
    state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    query = (
        select(LLMDetail, EventRecord)
        .join(EventRecord, EventRecord.id == LLMDetail.event_id)
        .order_by(EventRecord.ts.desc(), EventRecord.id.desc())
        .limit(limit)
    )
    if job_id:
        query = query.where(LLMDetail.job_id == job_id)
    if model:
        query = query.where(LLMDetail.model == model)
    if state:
        query = query.where(LLMDetail.state == state)
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
async def llm_stats(
    since: datetime | None = None,
    model: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(LLMDetail.model, func.count(), func.coalesce(func.sum(LLMDetail.input_tokens), 0), func.coalesce(func.sum(LLMDetail.output_tokens), 0), func.coalesce(func.sum(LLMDetail.cost_estimate), 0.0)).where(LLMDetail.state == "response")
    if since:
        query = query.join(EventRecord, EventRecord.id == LLMDetail.event_id).where(EventRecord.ts >= since)
    if model:
        query = query.where(LLMDetail.model == model)
    query = query.group_by(LLMDetail.model)
    rows = (await db.execute(query)).all()
    by_model = {
        row[0] or "unknown": {
            "responses": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "cost_estimate": float(row[4] or 0.0),
        }
        for row in rows
    }
    return {"by_model": by_model}


domain = EventDomain(
    model_name="llm",
    event_types=[
        "agent.llm.request",
        "agent.llm.response",
    ],
    detail_model=LLMDetail,
    router=router,
)
