import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set SQLite for tests before importing eventstore modules
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from pasloe.app import app
from pasloe.database import init_db, close_engine, get_engine


@pytest_asyncio.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await close_engine()


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_register_source(client):
    resp = await client.post("/sources", json={
        "id": "supervisor",
        "kind": "supervisor",
        "metadata": {"version": "0.1.0"}
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "supervisor"
    assert data["kind"] == "supervisor"


@pytest.mark.asyncio
async def test_register_duplicate_source(client):
    payload = {"id": "agent-gen0", "kind": "agent", "metadata": {"gen": 0}}
    await client.post("/sources", json=payload)
    resp = await client.post("/sources", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_sources(client):
    await client.post("/sources", json={"id": "ci", "kind": "ci", "metadata": {}})
    resp = await client.get("/sources")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "ci" in ids


@pytest.mark.asyncio
async def test_append_event(client):
    await client.post("/sources", json={"id": "supervisor", "kind": "supervisor", "metadata": {}})
    resp = await client.post("/events", json={
        "source_id": "supervisor",
        "type": "startup",
        "data": {"version": "0.1.0"}
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "startup"
    assert data["source_id"] == "supervisor"


@pytest.mark.asyncio
async def test_append_event_unregistered_source(client):
    resp = await client.post("/events", json={
        "source_id": "ghost",
        "type": "startup",
        "data": {}
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_query_events_by_source(client):
    await client.post("/sources", json={"id": "agent-gen0", "kind": "agent", "metadata": {}})
    await client.post("/events", json={"source_id": "agent-gen0", "type": "session_start", "data": {}})
    await client.post("/events", json={"source_id": "agent-gen0", "type": "turn_start", "data": {}})

    resp = await client.get("/events?source=agent-gen0")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 2
    assert all(e["source_id"] == "agent-gen0" for e in events)


@pytest.mark.asyncio
async def test_query_events_by_type(client):
    await client.post("/sources", json={"id": "agent-gen0", "kind": "agent", "metadata": {}})
    await client.post("/events", json={"source_id": "agent-gen0", "type": "session_start", "data": {}})
    await client.post("/events", json={"source_id": "agent-gen0", "type": "llm_request", "data": {}})

    resp = await client.get("/events?type=llm_request")
    assert resp.status_code == 200
    events = resp.json()
    assert all(e["type"] == "llm_request" for e in events)


@pytest.mark.asyncio
async def test_llm_response_data_promotion(client):
    """When an llm_response event is appended, data is promoted to llm_responses table."""
    await client.post("/sources", json={"id": "agent-gen0", "kind": "agent", "metadata": {}})
    resp = await client.post("/events", json={
        "source_id": "agent-gen0",
        "type": "llm_response",
        "data": {
            "model": "gemini-2.5-pro",
            "prompt_tokens": 1234,
            "completion_tokens": 456,
            "total_tokens": 1690,
            "latency_ms": 800,
            "cost": 0.0012
        }
    })
    assert resp.status_code == 201
    # We verify the event was stored; a separate endpoint for llm_responses can be added later


@pytest.mark.asyncio
async def test_llm_response_validation_error(client):
    await client.post("/sources", json={"id": "agent-validate", "kind": "agent", "metadata": {}})
    resp = await client.post("/events", json={
        "source_id": "agent-validate",
        "type": "llm_response",
        "data": {
            "prompt_tokens": 10,
            "completion_tokens": 5
        }
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stats(client):
    await client.post("/sources", json={"id": "supervisor", "kind": "supervisor", "metadata": {}})
    await client.post("/events", json={"source_id": "supervisor", "type": "startup", "data": {}})
    await client.post("/events", json={"source_id": "supervisor", "type": "shutdown", "data": {}})

    resp = await client.get("/events/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_events" in data
    assert data["total_events"] >= 2


@pytest.mark.asyncio
async def test_query_events_cursor_pagination(client):
    await client.post("/sources", json={"id": "pager", "kind": "agent", "metadata": {}})
    await client.post("/events", json={"source_id": "pager", "type": "e1", "data": {}})
    await client.post("/events", json={"source_id": "pager", "type": "e2", "data": {}})
    await client.post("/events", json={"source_id": "pager", "type": "e3", "data": {}})

    first = await client.get("/events", params={"source": "pager", "limit": 2, "order": "asc"})
    assert first.status_code == 200
    first_events = first.json()
    assert len(first_events) == 2
    next_cursor = first.headers.get("x-next-cursor")
    assert next_cursor is not None

    second = await client.get(
        "/events",
        params={"source": "pager", "limit": 2, "order": "asc", "cursor": next_cursor},
    )
    assert second.status_code == 200
    second_events = second.json()
    assert len(second_events) == 1
    assert second.headers.get("x-next-cursor") is None
    assert [e["type"] for e in first_events + second_events] == ["e1", "e2", "e3"]


@pytest.mark.asyncio
async def test_query_events_invalid_cursor(client):
    resp = await client.get("/events", params={"cursor": "not-a-cursor"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_close_engine_recreates_engine():
    await close_engine()
    await init_db()
    first_engine = get_engine()
    await close_engine()
    await init_db()
    second_engine = get_engine()
    assert first_engine is not second_engine
    await close_engine()
