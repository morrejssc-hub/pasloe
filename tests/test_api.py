"""Integration tests for the Pasloe HTTP API."""
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.pasloe.app import app
from src.pasloe.database import close_engine, get_session_factory, init_db
from src.pasloe.domains import discover_domains
from src.pasloe.pipeline import PipelineConfig, PipelineRuntime

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="async SQLite event loop interaction hangs on Python 3.14 (ADR-0008); E2E on Postgres passes",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    # DB_TYPE and SQLITE_PATH are set in tests/conftest.py before module import
    from src.pasloe.config import get_settings
    get_settings.cache_clear()  # ensure fresh settings per test

    app.state.domain_registry = {domain.model_name: domain for domain in discover_domains()}
    await init_db()
    pipeline = PipelineRuntime(
        session_factory=get_session_factory(),
        domain_registry=app.state.domain_registry,
        config=PipelineConfig(
            poll_interval_seconds=0.01,
            batch_size=64,
            lease_seconds=5,
            retry_base_seconds=0.05,
            retry_max_seconds=1.0,
        ),
    )
    await pipeline.start()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    await pipeline.stop()
    await close_engine()
    get_settings.cache_clear()


async def _wait_event_visible(client, event_id: str, timeout_s: float = 2.0) -> None:
    import asyncio

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        r = await client.get(f"/events?id={event_id}")
        if r.status_code == 200 and r.json():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"event {event_id} did not become visible within {timeout_s}s")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class TestSources:
    @pytest.mark.asyncio
    async def test_register_source_returns_201(self, client):
        r = await client.post("/sources", json={"id": "src1"})
        assert r.status_code == 201
        assert r.json()["id"] == "src1"

    @pytest.mark.asyncio
    async def test_register_source_upsert_returns_200(self, client):
        await client.post("/sources", json={"id": "src2", "metadata": {"v": 1}})
        r = await client.post("/sources", json={"id": "src2", "metadata": {"v": 2}})
        assert r.status_code == 200
        assert r.json()["metadata"]["v"] == 2

    @pytest.mark.asyncio
    async def test_list_sources(self, client):
        await client.post("/sources", json={"id": "ls1"})
        r = await client.get("/sources")
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()]
        assert "ls1" in ids

    @pytest.mark.asyncio
    async def test_get_source(self, client):
        await client.post("/sources", json={"id": "gs1"})
        r = await client.get("/sources/gs1")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_get_source_not_found(self, client):
        r = await client.get("/sources/nope")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Events — append
# ---------------------------------------------------------------------------

class TestAppendEvent:
    @pytest.mark.asyncio
    async def test_append_auto_registers_source(self, client):
        r = await client.post("/events", json={"source_id": "new-src", "type": "ping", "data": {}})
        assert r.status_code == 202
        body = r.json()
        assert body["source_id"] == "new-src"
        assert body["warnings"] == []
        assert body["status"] == "accepted"
        await _wait_event_visible(client, body["id"])

    @pytest.mark.asyncio
    async def test_append_returns_empty_warnings_without_projection(self, client):
        r = await client.post("/events", json={"source_id": "s", "type": "t", "data": {"x": 1}})
        assert r.status_code == 202
        assert r.json()["warnings"] == []
        await _wait_event_visible(client, r.json()["id"])

    @pytest.mark.asyncio
    async def test_deleted_endpoint_events_by_id_gone(self, client):
        r = await client.get("/events/some-uuid")
        # Should be 404 (no such path), not 200
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_deleted_endpoint_schemas_gone(self, client):
        assert (await client.post("/schemas", json={})).status_code == 404

    @pytest.mark.asyncio
    async def test_deleted_endpoint_s3_gone(self, client):
        assert (await client.post("/artifacts/presign", json={})).status_code == 404


# ---------------------------------------------------------------------------
# Events — query
# ---------------------------------------------------------------------------

class TestQueryEvents:
    @pytest.mark.asyncio
    async def test_query_by_source(self, client):
        r0 = await client.post("/events", json={"source_id": "qs", "type": "t", "data": {}})
        await _wait_event_visible(client, r0.json()["id"])
        r = await client.get("/events?source=qs")
        assert r.status_code == 200
        assert all(e["source_id"] == "qs" for e in r.json())

    @pytest.mark.asyncio
    async def test_query_by_type(self, client):
        r0 = await client.post("/events", json={"source_id": "qt", "type": "special", "data": {}})
        await _wait_event_visible(client, r0.json()["id"])
        r = await client.get("/events?type=special")
        assert r.status_code == 200
        assert all(e["type"] == "special" for e in r.json())

    @pytest.mark.asyncio
    async def test_query_by_id(self, client):
        r1 = await client.post("/events", json={"source_id": "qi", "type": "t", "data": {}})
        event_id = r1.json()["id"]
        await _wait_event_visible(client, event_id)
        r2 = await client.get(f"/events?id={event_id}")
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        assert r2.json()[0]["id"] == event_id

    @pytest.mark.asyncio
    async def test_invalid_cursor_returns_400(self, client):
        r = await client.get("/events?cursor=notvalid")
        assert r.status_code == 400

class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self, client):
        r0 = await client.post("/events", json={"source_id": "st", "type": "ev", "data": {}})
        await _wait_event_visible(client, r0.json()["id"])
        r = await client.get("/events/stats")
        assert r.status_code == 200
        body = r.json()
        assert "total_events" in body
        assert "by_source" in body
        assert "by_type" in body
        assert body["total_events"] >= 1


class TestDomainEndpoints:
    @pytest.mark.asyncio
    async def test_tasks_endpoint_and_stats(self, client):
        for payload in (
            {"source_id": "sup", "type": "supervisor.task.created", "data": {"task_id": "t1", "goal": "do work", "team": "backend"}},
            {"source_id": "sup", "type": "supervisor.task.completed", "data": {"task_id": "t1", "summary": "done", "team": "backend"}},
        ):
            r = await client.post("/events", json=payload)
            await _wait_event_visible(client, r.json()["id"])

        listed = await client.get("/tasks?task_id=t1")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        stats = await client.get("/tasks/stats?team=backend")
        assert stats.status_code == 200
        assert stats.json()["event_counts_by_state"]["created"] == 1
        assert stats.json()["terminal_task_count"] == 1

    @pytest.mark.asyncio
    async def test_jobs_endpoint_and_stats(self, client):
        for payload in (
            {"source_id": "agent", "type": "agent.job.started", "data": {"job_id": "j1", "task_id": "t1", "role": "planner"}},
            {"source_id": "agent", "type": "agent.job.completed", "data": {"job_id": "j1", "task_id": "t1", "summary": "ok", "role": "planner"}},
        ):
            r = await client.post("/events", json=payload)
            await _wait_event_visible(client, r.json()["id"])

        listed = await client.get("/jobs?job_id=j1")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        stats = await client.get("/jobs/stats?role=planner")
        assert stats.status_code == 200
        assert stats.json()["event_counts_by_state"]["started"] == 1
        assert stats.json()["terminal_job_count"] == 1

    @pytest.mark.asyncio
    async def test_llm_endpoint_and_stats(self, client):
        for payload in (
            {"source_id": "agent", "type": "agent.llm.request", "data": {"job_id": "j1", "model": "gpt-4o-mini", "iteration": 1}},
            {"source_id": "agent", "type": "agent.llm.response", "data": {"job_id": "j1", "model": "gpt-4o-mini", "finish_reason": "stop", "input_tokens": 10, "output_tokens": 5, "duration_ms": 100}},
        ):
            r = await client.post("/events", json=payload)
            await _wait_event_visible(client, r.json()["id"])

        listed = await client.get("/llm?job_id=j1")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        stats = await client.get("/llm/stats?model=gpt-4o-mini")
        assert stats.status_code == 200
        assert stats.json()["by_model"]["gpt-4o-mini"]["input_tokens"] == 10

    @pytest.mark.asyncio
    async def test_tools_endpoint_and_stats(self, client):
        for payload in (
            {"source_id": "agent", "type": "agent.tool.exec", "data": {"job_id": "j1", "tool_name": "bash", "tool_call_id": "tc1"}},
            {"source_id": "agent", "type": "agent.tool.result", "data": {"job_id": "j1", "tool_name": "bash", "tool_call_id": "tc1", "success": True, "duration_ms": 12}},
        ):
            r = await client.post("/events", json=payload)
            await _wait_event_visible(client, r.json()["id"])

        listed = await client.get("/tools?job_id=j1")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        stats = await client.get("/tools/stats")
        assert stats.status_code == 200
        assert stats.json()["by_tool"]["bash"]["successes"] == 1


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class TestWebhooks:
    @pytest.mark.asyncio
    async def test_register_webhook(self, client):
        r = await client.post("/webhooks", json={"url": "http://test.host/h"})
        assert r.status_code == 201
        data = r.json()
        assert data["url"] == "http://test.host/h"
        assert "id" in data
        assert "has_secret" in data  # secret is not exposed directly

    @pytest.mark.asyncio
    async def test_register_webhook_idempotent(self, client):
        r1 = await client.post("/webhooks", json={"url": "http://x.test/h", "secret": "a"})
        r2 = await client.post("/webhooks", json={"url": "http://x.test/h", "secret": "b"})
        assert r1.status_code == 201
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]
        assert r2.json()["has_secret"] is True  # secret "b" is set

    @pytest.mark.asyncio
    async def test_list_webhooks(self, client):
        await client.post("/webhooks", json={"url": "http://list.test/h"})
        r = await client.get("/webhooks")
        assert r.status_code == 200
        assert any(w["url"] == "http://list.test/h" for w in r.json())

    @pytest.mark.asyncio
    async def test_delete_webhook(self, client):
        r = await client.post("/webhooks", json={"url": "http://del.test/h"})
        wh_id = r.json()["id"]
        r2 = await client.delete(f"/webhooks/{wh_id}")
        assert r2.status_code == 204
        r3 = await client.get("/webhooks")
        assert not any(w["id"] == wh_id for w in r3.json())

    @pytest.mark.asyncio
    async def test_delete_webhook_not_found(self, client):
        r = await client.delete("/webhooks/nonexistent")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_post_event_triggers_delivery(self, client):
        """Delivery is background — just verify no error on POST /events."""
        await client.post("/sources", json={"id": "src-wh"})
        await client.post("/webhooks", json={"url": "http://nowhere.invalid/h"})
        r = await client.post("/events", json={
            "source_id": "src-wh", "type": "task.submit", "data": {},
        })
        assert r.status_code == 202
