from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from ..models import Base


class EventDetailBase(Base):
    __abstract__ = True

    @classmethod
    def from_event(cls, event_id: str, event_type: str, data: dict[str, Any]):
        raise NotImplementedError

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class EventDomain:
    model_name: str
    event_types: list[str]
    detail_model: type[EventDetailBase]
    router: APIRouter


def model_name_from_event_type(event_type: str) -> str | None:
    parts = (event_type or "").split(".", 2)
    if len(parts) != 3:
        return None
    return parts[1] or None


def discover_domains() -> list[EventDomain]:
    from .jobs import domain as jobs_domain
    from .llm import domain as llm_domain
    from .tasks import domain as tasks_domain
    from .tools import domain as tools_domain

    return [jobs_domain, tasks_domain, llm_domain, tools_domain]
