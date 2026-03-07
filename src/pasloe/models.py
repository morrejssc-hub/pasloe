from datetime import datetime
from typing import Optional, Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, String, DateTime, Index, ForeignKey, Integer, Float, Text, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

from .config import is_sqlite

# Base model
Base = declarative_base()

# Use dialect-specific types
if is_sqlite():
    from sqlalchemy import JSON
    JSON_TYPE = JSON
    # Vector not available in SQLite by default, use Text as fallback for storage
    VECTOR_TYPE = Text
    # SQLite doesn't support ARRAY; store event_types as JSON array
    ARRAY_TEXT_TYPE = JSON
else:
    from sqlalchemy.dialects.postgresql import JSONB, ARRAY
    from pgvector.sqlalchemy import Vector
    JSON_TYPE = JSONB
    VECTOR_TYPE = Vector(1536)
    ARRAY_TEXT_TYPE = ARRAY(String)


class SourceRecord(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True)  # e.g., 'agent-gen0', 'supervisor'
    kind = Column(String, nullable=False)   # e.g., 'agent', 'supervisor', 'ci'
    metadata_ = Column("metadata", JSON_TYPE, nullable=False, server_default='{}')
    registered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    events = relationship("EventRecord", back_populates="source")


class EventRecord(Base):
    __tablename__ = "events"

    # PG_UUID works in PG, for SQLite we store as string but SQLAlchemy handles it
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    type = Column(String, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    data = Column(JSON_TYPE, nullable=False, server_default='{}')
    session_id = Column(PG_UUID(as_uuid=True), nullable=True)
    embedding = Column(VECTOR_TYPE, nullable=True)

    source = relationship("SourceRecord", back_populates="events")
    # Specialized data promotion (One-to-One)
    llm_response = relationship("LLMResponseRecord", back_populates="event", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_events_ts', 'ts'),
        Index('idx_events_source', 'source_id'),
        Index('idx_events_type', 'type'),
        Index('idx_events_session', 'session_id'),
    )


class WebhookRecord(Base):
    """Registered webhook: EventStore calls this URL when matching events are written."""
    __tablename__ = "webhooks"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    url = Column(String, nullable=False)
    event_types = Column(ARRAY_TEXT_TYPE, nullable=False, server_default='[]')
    secret = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LLMResponseRecord(Base):
    """
    Example of 'Data-to-Table Promotion': 
    Promoting key 'data' fields of an 'llm_response' event to a structured table.
    """
    __tablename__ = "llm_responses"

    event_id = Column(PG_UUID(as_uuid=True), ForeignKey("events.id"), primary_key=True)
    model = Column(String, nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)

    event = relationship("EventRecord", back_populates="llm_response")


class SourceCreate(BaseModel):
    id: str
    kind: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventCreate(BaseModel):
    source_id: str
    type: str = Field(min_length=1)
    data: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_type_specific_payload(self):
        if self.type == "llm_response":
            payload = LLMResponseData.model_validate(self.data)
            self.data = payload.model_dump()
        return self


class LLMResponseData(BaseModel):
    model: str = Field(min_length=1)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    latency_ms: Optional[int] = Field(default=None, ge=0)
    cost: Optional[float] = Field(default=None, ge=0)


class Event(BaseModel):
    id: UUID
    source_id: str
    type: str
    ts: datetime
    data: Dict[str, Any]
    session_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


# --- Webhook Pydantic models ---

class WebhookCreate(BaseModel):
    url: str = Field(min_length=1)
    event_types: List[str] = Field(default_factory=list)
    secret: Optional[str] = None


class Webhook(BaseModel):
    id: UUID
    url: str
    event_types: List[str]
    secret: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
