"""Tests for webhook delivery and model."""
import pytest
from src.pasloe.models import WebhookRecord, WebhookCreate, WebhookResponse

def test_webhook_record_table_name():
    assert WebhookRecord.__tablename__ == "webhooks"

def test_webhook_create_defaults():
    wh = WebhookCreate(url="http://localhost:9000/hooks")
    assert wh.event_types == []
    assert wh.secret == ""
    assert wh.source_filter is None
