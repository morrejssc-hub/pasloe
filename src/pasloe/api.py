from datetime import datetime
from typing import Optional, List, Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import SourceCreate, EventCreate, Event, WebhookCreate, Webhook
from . import store
from . import s3
from .config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)):
    expected_api_key = get_settings().api_key
    if expected_api_key and api_key != expected_api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")

router = APIRouter(dependencies=[Depends(verify_api_key)])

class ArtifactPresignRequest(BaseModel):
    filename: str
    content_type: str

class ArtifactPresignResponse(BaseModel):
    upload_url: str
    access_url: str
    object_name: str


# --- Source endpoints ---

class SourceResponse(BaseModel):
    id: str
    kind: str
    metadata: Dict[str, Any]
    registered_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def register_source(source: SourceCreate, db: AsyncSession = Depends(get_session)):
    try:
        record = await store.register_source(db, source)
    except store.DuplicateSourceError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return SourceResponse(id=record.id, kind=record.kind, metadata=record.metadata_, registered_at=record.registered_at)


@router.get("/sources", response_model=List[SourceResponse])
async def list_sources(db: AsyncSession = Depends(get_session)):
    records = await store.list_sources(db)
    return [SourceResponse(id=r.id, kind=r.kind, metadata=r.metadata_, registered_at=r.registered_at) for r in records]


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: AsyncSession = Depends(get_session)):
    record = await store.get_source(db, source_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    return SourceResponse(id=record.id, kind=record.kind, metadata=record.metadata_, registered_at=record.registered_at)


# --- Event endpoints ---

@router.post("/events", response_model=Event, status_code=201)
async def append_event(event: EventCreate, db: AsyncSession = Depends(get_session)):
    try:
        record = await store.append_event(db, event)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return record


@router.get("/events", response_model=List[Event])
async def query_events(
    response: Response,
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    type: Optional[str] = Query(None, alias="type"),
    session_id: Optional[UUID] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_session),
):
    try:
        records, next_cursor = await store.query_events(
            db,
            since=since,
            until=until,
            source=source,
            type_=type,
            session_id=session_id,
            cursor=cursor,
            limit=limit,
            order=order,
        )
    except store.InvalidCursorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return records


@router.get("/events/stats")
async def get_stats(db: AsyncSession = Depends(get_session)) -> Dict[str, Any]:
    return await store.get_stats(db)


@router.get("/events/{event_id}", response_model=Event)
async def get_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_session),
):
    record = await store.get_event_by_id(db, event_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")
    return record


# --- Webhook endpoints ---

@router.post("/webhooks", response_model=Webhook, status_code=201)
async def create_webhook(webhook: WebhookCreate, db: AsyncSession = Depends(get_session)):
    record = await store.create_webhook(db, webhook)
    return Webhook(
        id=record.id,
        url=record.url,
        event_types=record.event_types or [],
        secret=record.secret,
        created_at=record.created_at,
    )


@router.get("/webhooks", response_model=List[Webhook])
async def list_webhooks(db: AsyncSession = Depends(get_session)):
    records = await store.list_webhooks(db)
    return [
        Webhook(
            id=r.id,
            url=r.url,
            event_types=r.event_types or [],
            secret=r.secret,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: UUID, db: AsyncSession = Depends(get_session)):
    deleted = await store.delete_webhook(db, webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")

# --- Artifact endpoints ---

@router.post("/artifacts/presign", response_model=ArtifactPresignResponse)
async def create_artifact_presign(req: ArtifactPresignRequest):
    try:
        result = await s3.generate_presigned_url(req.filename, req.content_type)
        return ArtifactPresignResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")
