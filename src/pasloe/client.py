"""EventStore HTTP client — shared by Agent and Supervisor.

Extracted from agent/src/agent/events.py and placed here so both
consumers can import from the same package without a separate core repo.

Usage:
    from pasloe.client import EventStoreClient, EventStoreError, Event
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import httpx


@dataclass
class Event:
    id: str
    source_id: str
    type: str
    ts: str
    data: dict[str, Any]
    session_id: Optional[str] = None


class EventStoreError(Exception):
    pass


class EventStoreClient:
    def __init__(self, base_url: str, agent_id: str, session_id: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.session_id = session_id
        self._client = httpx.Client(base_url=self.base_url, timeout=10.0)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Source registration ──────────────────────────────────────────────

    def register_source(self, kind: str = "agent", metadata: dict | None = None) -> None:
        """Register this agent as an event source (idempotent — ignores 409)."""
        try:
            resp = self._client.post("/sources", json={
                "id": self.agent_id,
                "kind": kind,
                "metadata": metadata or {},
            })
            if resp.status_code not in (201, 409):
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"register_source failed: {e}") from e

    # ── Event writing ────────────────────────────────────────────────────

    def append(self, type: str, data: dict[str, Any] | None = None) -> Event:
        """Write an event to EventStore."""
        payload: dict[str, Any] = {
            "source_id": self.agent_id,
            "type": type,
            "data": data or {},
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        resp = self._client.post("/events", json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"append_event failed ({type}): {e}") from e
        return _parse_event(resp.json())

    # ── Event reading ────────────────────────────────────────────────────

    def get_event(self, event_id: str) -> Event:
        """Get a single event by ID using the dedicated endpoint."""
        resp = self._client.get(f"/events/{event_id}")
        if resp.status_code == 404:
            raise EventStoreError(f"Event {event_id} not found")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"get_event failed: {e}") from e
        return _parse_event(resp.json())

    def query(
        self,
        type: str | None = None,
        source: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        order: str = "asc",
        cursor: str | None = None,
    ) -> list[Event]:
        """Query events from EventStore."""
        params: dict[str, Any] = {"limit": limit, "order": order}
        if type:
            params["type"] = type
        if source:
            params["source"] = source
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if cursor:
            params["cursor"] = cursor

        resp = self._client.get("/events", params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"query_events failed: {e}") from e
        return [_parse_event(r) for r in resp.json()]

    def get_stats(self) -> dict[str, Any]:
        resp = self._client.get("/events/stats")
        resp.raise_for_status()
        return resp.json()

    # ── Webhook management ───────────────────────────────────────────────

    def register_webhook(self, url: str, event_types: list[str], secret: str | None = None) -> str:
        """Register a webhook. Returns the webhook ID."""
        resp = self._client.post("/webhooks", json={
            "url": url,
            "event_types": event_types,
            "secret": secret,
        })
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"register_webhook failed: {e}") from e
        return resp.json()["id"]

    def delete_webhook(self, webhook_id: str) -> None:
        """Deregister a webhook by ID."""
        resp = self._client.delete(f"/webhooks/{webhook_id}")
        if resp.status_code == 404:
            return  # Already gone — idempotent
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EventStoreError(f"delete_webhook failed: {e}") from e

    def list_webhooks(self) -> list[dict[str, Any]]:
        resp = self._client.get("/webhooks")
        resp.raise_for_status()
        return resp.json()


def _parse_event(raw: dict) -> Event:
    return Event(
        id=str(raw["id"]),
        source_id=raw["source_id"],
        type=raw["type"],
        ts=raw["ts"] if isinstance(raw["ts"], str) else raw["ts"].isoformat(),
        data=raw.get("data", {}),
        session_id=raw.get("session_id"),
    )
