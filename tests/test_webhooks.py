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


from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.pasloe.webhook_delivery import compute_signature, verify_signature, deliver_to_webhook


def test_compute_signature_consistency():
    body = b'{"type": "task.submit"}'
    sig1 = compute_signature("secret", body)
    sig2 = compute_signature("secret", body)
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_verify_signature_valid():
    body = b'{"type": "task.submit"}'
    sig = compute_signature("secret", body)
    assert verify_signature("secret", body, sig) is True


def test_verify_signature_invalid():
    body = b'{"type": "task.submit"}'
    assert verify_signature("secret", body, "sha256=badhex") is False


def test_verify_signature_empty_secret_skips():
    """Empty secret = no signature check (unsigned webhook)."""
    body = b'{}'
    assert verify_signature("", body, "") is True


@pytest.mark.asyncio
async def test_deliver_to_webhook_success():
    from src.pasloe.models import WebhookRecord
    wh = WebhookRecord(
        id="wh1", url="http://localhost:9999/hooks",
        secret="sec", event_types=[], source_filter=None,
    )
    event_payload = {
        "id": "e1", "source_id": "src", "type": "task.submit",
        "ts": datetime.now(timezone.utc).isoformat(), "data": {},
    }
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.pasloe.webhook_delivery.httpx.AsyncClient", return_value=mock_client):
        result = await deliver_to_webhook(wh, event_payload)

    assert result is True
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["headers"]["X-Pasloe-Signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_deliver_to_webhook_retries_on_failure():
    import httpx as _httpx
    from src.pasloe.models import WebhookRecord
    wh = WebhookRecord(
        id="wh2", url="http://fail.test/hooks",
        secret="", event_types=[], source_filter=None,
    )
    event_payload = {"id": "e2", "source_id": "s", "type": "x", "ts": "2026-01-01T00:00:00", "data": {}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))

    with patch("src.pasloe.webhook_delivery.httpx.AsyncClient", return_value=mock_client):
        with patch("src.pasloe.webhook_delivery.asyncio.sleep", AsyncMock()):
            result = await deliver_to_webhook(wh, event_payload)

    assert result is False
    assert mock_client.post.call_count == 3  # 3 attempts
