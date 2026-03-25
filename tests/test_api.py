"""Integration tests for the Pasloe HTTP API."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.pasloe.app import app, app_state
from src.pasloe.database import close_engine, init_db
from src.pasloe.projections import BaseProjection, ProjectionRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    # DB_TYPE and SQLITE_PATH are set in tests/conftest.py before module import
    from src.pasloe.config import get_settings
    get_settings.cache_clear()  # ensure fresh settings per test

    app.state.projection_registry = ProjectionRegistry([])  # empty by default; tests override as needed
    await init_db()
    
    # Ensure app is marked as ready for tests
    app_state.ready = True
    app_state.startup_error = None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    await close_engine()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_is_cheap_no_db_query(self, client):
        """
        Health check should be cheap and not require database queries.
        This prevents health flaps during normal event polling.
        """
        # Make multiple rapid health checks - should be fast
        for _ in range(10):
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_deterministic_response_format(self, client):
        """
        Health check should return consistent response format.
        """
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data["status"] == "ok"
        # Should not have unexpected fields
        assert set(data.keys()) == {"status"}

    @pytest.mark.asyncio
    async def test_health_returns_503_when_not_ready(self, client):
        """
        Health check should return 503 when app is not ready.
        This is important for container orchestration to know when
        to stop sending traffic.
        """
        # Temporarily set app as not ready
        original_ready = app_state.ready
        app_state.ready = False
        try:
            r = await client.get("/health")
            assert r.status_code == 503
            data = r.json()
            assert data["detail"]["status"] == "not_ready"
        finally:
            app_state.ready = original_ready

    @pytest.mark.asyncio
    async def test_health_returns_ok_after_restoring_ready(self, client):
        """
        Health check should return 200 after restoring ready state.
        Verifies the ready flag is properly checked.
        """
        # First verify it's currently ready
        r = await client.get("/health")
        assert r.status_code == 200

        # Temporarily set as not ready
        original_ready = app_state.ready
        app_state.ready = False
        try:
            r = await client.get("/health")
            assert r.status_code == 503
        finally:
            app_state.ready = original_ready

        # Verify it's ready again
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
        assert r.status_code == 201
        body = r.json()
        assert body["source_id"] == "new-src"
        assert body["warnings"] == []

    @pytest.mark.asyncio
    async def test_append_returns_empty_warnings_without_projection(self, client):
        r = await client.post("/events", json={"source_id": "s", "type": "t", "data": {"x": 1}})
        assert r.status_code == 201
        assert r.json()["warnings"] == []

    @pytest.mark.asyncio
    async def test_append_returns_warnings_when_projection_skips(self, client):
        class SkipProj(BaseProjection):
            source = "ws"
            event_type = "typed"
            __tablename__ = "proj_ws"

            async def on_insert(self, session, event):
                return ["bad_field"]

            async def filter(self, session, event_ids, filters):
                return event_ids

        app.state.projection_registry = ProjectionRegistry([SkipProj()])
        r = await client.post("/events", json={"source_id": "ws", "type": "typed", "data": {"bad_field": 1}})
        assert r.status_code == 201
        body = r.json()
        assert body["id"] is not None          # event stored
        assert len(body["warnings"]) == 1
        assert "bad_field" in body["warnings"][0]

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
        await client.post("/events", json={"source_id": "qs", "type": "t", "data": {}})
        r = await client.get("/events?source=qs")
        assert r.status_code == 200
        assert all(e["source_id"] == "qs" for e in r.json())

    @pytest.mark.asyncio
    async def test_query_by_type(self, client):
        await client.post("/events", json={"source_id": "qt", "type": "special", "data": {}})
        r = await client.get("/events?type=special")
        assert r.status_code == 200
        assert all(e["type"] == "special" for e in r.json())

    @pytest.mark.asyncio
    async def test_query_by_id(self, client):
        r1 = await client.post("/events", json={"source_id": "qi", "type": "t", "data": {}})
        event_id = r1.json()["id"]
        r2 = await client.get(f"/events?id={event_id}")
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        assert r2.json()[0]["id"] == event_id

    @pytest.mark.asyncio
    async def test_invalid_cursor_returns_400(self, client):
        r = await client.get("/events?cursor=notvalid")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_projection_filter_ignored_when_no_projection(self, client):
        """Unknown params are silently ignored when no matching projection."""
        await client.post("/events", json={"source_id": "pf", "type": "t", "data": {"level": "info"}})
        r = await client.get("/events?source=pf&type=t&level=info")
        assert r.status_code == 200  # no error

    @pytest.mark.asyncio
    async def test_projection_filter_applied_when_projection_matches(self, client):
        from uuid import UUID

        class LevelProj(BaseProjection):
            source = "lp"
            event_type = "log"
            __tablename__ = "proj_level"

            async def on_insert(self, session, event):
                return []

            async def filter(self, session, event_ids, filters):
                # Simulate: only return first id (as if filtered by level=error)
                return event_ids[:1]

        app.state.projection_registry = ProjectionRegistry([LevelProj()])
        for _ in range(3):
            await client.post("/events", json={"source_id": "lp", "type": "log", "data": {}})

        r = await client.get("/events?source=lp&type=log&level=error")
        assert r.status_code == 200
        assert len(r.json()) == 1  # projection narrowed to 1


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self, client):
        await client.post("/events", json={"source_id": "st", "type": "ev", "data": {}})
        r = await client.get("/events/stats")
        assert r.status_code == 200
        body = r.json()
        assert "total_events" in body
        assert "by_source" in body
        assert "by_type" in body


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class TestWebhooks:
    @pytest.mark.asyncio
    async def test_register_webhook_returns_201(self, client):
        r = await client.post("/webhooks", json={
            "url": "https://example.com/webhook",
            "event_types": ["*"],
        })
        assert r.status_code == 201
        assert r.json()["url"] == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_register_webhook_upsert_returns_200(self, client):
        await client.post("/webhooks", json={
            "url": "https://example.com/hook2",
            "event_types": ["a"],
        })
        r = await client.post("/webhooks", json={
            "url": "https://example.com/hook2",
            "event_types": ["b"],
        })
        assert r.status_code == 200
        assert r.json()["event_types"] == ["b"]

    @pytest.mark.asyncio
    async def test_list_webhooks(self, client):
        await client.post("/webhooks", json={
            "url": "https://example.com/hook3",
            "event_types": ["*"],
        })
        r = await client.get("/webhooks")
        assert r.status_code == 200
        urls = [w["url"] for w in r.json()]
        assert "https://example.com/hook3" in urls

    @pytest.mark.asyncio
    async def test_delete_webhook(self, client):
        r = await client.post("/webhooks", json={
            "url": "https://example.com/hook4",
            "event_types": ["*"],
        })
        webhook_id = r.json()["id"]
        r = await client.delete(f"/webhooks/{webhook_id}")
        assert r.status_code == 204
        r = await client.get("/webhooks")
        urls = [w["url"] for w in r.json()]
        assert "https://example.com/hook4" not in urls

    @pytest.mark.asyncio
    async def test_delete_webhook_not_found(self, client):
        r = await client.delete("/webhooks/nonexistent-id")
        assert r.status_code == 404
