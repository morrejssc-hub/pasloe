"""Tests for webhook delivery and model."""
import pytest
import pytest_asyncio
from src.pasloe.models import WebhookRecord, WebhookCreate, WebhookResponse
from src.pasloe import store
from src.pasloe.database import close_engine, init_db, get_session_factory

def test_webhook_record_table_name():
    assert WebhookRecord.__tablename__ == "webhooks"

def test_webhook_create_defaults():
    wh = WebhookCreate(url="http://localhost:9000/hooks")
    assert wh.event_types == []
    assert wh.secret == ""
    assert wh.source_filter is None


@pytest_asyncio.fixture
async def db():
    from src.pasloe.config import get_settings
    get_settings.cache_clear()
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()
    await close_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_webhook(db):
    wh = await store.create_or_update_webhook(db, WebhookCreate(
        url="http://localhost:9000/hooks",
        secret="s3cr3t",
        event_types=["task.submit"],
    ))
    assert wh.id
    assert wh.url == "http://localhost:9000/hooks"


@pytest.mark.asyncio
async def test_create_webhook_idempotent(db):
    body = WebhookCreate(url="http://localhost:9000/hooks", secret="a")
    wh1 = await store.create_or_update_webhook(db, body)
    body2 = WebhookCreate(url="http://localhost:9000/hooks", secret="b")
    wh2 = await store.create_or_update_webhook(db, body2)
    assert wh1.id == wh2.id
    assert wh2.secret == "b"  # updated


@pytest.mark.asyncio
async def test_list_webhooks_for_event_type_filter(db):
    await store.create_or_update_webhook(db, WebhookCreate(
        url="http://a.test/h", event_types=["task.submit"],
    ))
    await store.create_or_update_webhook(db, WebhookCreate(
        url="http://b.test/h", event_types=[],  # all types
    ))
    matches = await store.list_webhooks_for_event(db, "task.submit", "src1")
    urls = [w.url for w in matches]
    assert "http://a.test/h" in urls
    assert "http://b.test/h" in urls


@pytest.mark.asyncio
async def test_list_webhooks_for_event_type_no_match(db):
    await store.create_or_update_webhook(db, WebhookCreate(
        url="http://c.test/h", event_types=["job.completed"],
    ))
    matches = await store.list_webhooks_for_event(db, "task.submit", "src1")
    assert not any(w.url == "http://c.test/h" for w in matches)


@pytest.mark.asyncio
async def test_delete_webhook(db):
    wh = await store.create_or_update_webhook(db, WebhookCreate(url="http://d.test/h"))
    deleted = await store.delete_webhook(db, wh.id)
    assert deleted is True
    result = await store.get_webhook(db, wh.id)
    assert result is None
