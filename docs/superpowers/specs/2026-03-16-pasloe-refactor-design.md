# Pasloe Refactor: Semantically Agnostic Event Store

**Date:** 2026-03-16
**Status:** Approved

---

## Goal

Simplify Pasloe into a pure, semantically agnostic append-only event store. Events are the single source of truth. All acceleration structures (projections) are purely optional optimizations — their absence or destruction never causes data loss, only query performance degradation.

---

## What Gets Removed

| Component | Reason |
|-----------|--------|
| Webhook module (endpoints + DB table + async trigger) | Clients handle delivery themselves |
| S3 artifact presign | Clients decide their own storage |
| Python and Rust client libraries | Pasloe exposes standard HTTP API only |
| `event_type_schemas` table + `/schemas` endpoints | Replaced by code-defined projections |
| All `promoted_*` dynamic tables | Replaced by Alembic-managed static projection tables |
| `/promoted/{source_id}/{type}` endpoint | Merged into `GET /events` |
| `embedding` column on events | ML-specific, not part of core store |
| Schema rotation (end_time mechanism, multi-version tables) | Complexity without benefit in new design |
| `GET /events/{id}` endpoint | Covered by `GET /events?id=<uuid>` |

Web UI is preserved unchanged pending backend stabilization.

---

## Data Model

### `events` (source of truth, unchanged except embedding removed)

```
id          UUID7, PK
source_id   String, FK → sources.id
type        String
ts          DateTime with TZ  (server-generated)
data        JSON / JSONB
```

Indexes: `(ts)`, `(source_id)`, `(type)`

### `sources` (unchanged)

```
id            String, PK  (user-defined)
metadata      JSON
registered_at DateTime with TZ
```

**Change:** Source auto-registration — `POST /events` with an unknown `source_id` silently creates the source with empty metadata. Explicit `POST /sources` remains for registering with metadata.

---

## Projection System

Projections are code-defined acceleration tables for known, high-frequency event types. They are **purely additive**: events are always recorded in the `events` table first; projection writes are best-effort side effects.

### BaseProjection Interface

```python
class BaseProjection:
    source: str       # matched source_id
    event_type: str   # matched event type

    def matches(self, source_id: str, event_type: str) -> bool

    async def on_insert(self, session, event: EventRecord) -> None
    # Field extraction rules:
    #   - missing field → NULL
    #   - extra field not in projection → raise ValidationError (→ HTTP 400)

    async def filter(
        self,
        session,
        event_ids: list[UUID],
        filters: dict,
    ) -> list[UUID]
    # Returns ordered subset of event_ids matching projection-specific filters.
    # If filters contain no projection fields, returns event_ids unchanged.
```

### ProjectionRegistry

Automatically discovers all `BaseProjection` subclasses at startup.

```python
# Event write path (called once per event insert)
await registry.on_event(session, event)

# Query path (called if projection-specific filters are present)
filtered_ids = await registry.filter(source, event_type, event_ids, filters)
# Returns None if no projection matches → caller uses event_ids as-is
```

Adding a new projection requires only:
1. Define a new `BaseProjection` subclass with its SQLAlchemy table
2. Write an Alembic migration for the new table
3. No changes to main application code

### Projection Table Lifecycle

- **Create:** Alembic migration adds the table
- **Populate:** `on_insert` writes new matching events going forward
- **Destructive change:** Write a new Alembic migration (alter or drop+recreate table). Old projection data is lost; historical events remain queryable via the raw `events` table.
- **No backfill:** After destructive changes, projection accumulates from new events only.

### Example Projection

```python
class LLMCallProjection(BaseProjection):
    __tablename__ = "proj_llm_call"
    source = "agent"
    event_type = "llm_call"

    event_id = Column(UUID, ForeignKey("events.id"), primary_key=True)
    model    = Column(String, index=True)
    tokens   = Column(Integer)
    cost     = Column(Float, index=True)
```

---

## API Endpoints

### Kept

```
GET  /health
GET  /ui
POST /sources
GET  /sources
GET  /sources/{source_id}
POST /events
GET  /events
GET  /events/stats
```

### Removed

```
GET  /events/{id}
POST /schemas, GET /schemas, GET /schemas/{schema_id}
GET  /promoted/{source_id}/{type}
POST /webhooks, GET /webhooks, DELETE /webhooks/{webhook_id}
POST /artifacts/presign
```

---

## GET /events — Unified Query

### Standard filters (events table)

| Param | Description |
|-------|-------------|
| `id=<uuid>` | Fetch single event by ID |
| `source=<str>` | Filter by source_id |
| `type=<str>` | Filter by event type |
| `since=<iso>` | Events at or after timestamp |
| `until=<iso>` | Events before or at timestamp |
| `cursor=<str>` | Pagination cursor (`ts\|uuid` format) |
| `limit=<int>` | Max results (1–1000, default 100) |
| `order=asc\|desc` | Sort order (default asc) |

### Projection filters (field-level, ignored if no matching projection)

| Syntax | Column type | Semantics |
|--------|-------------|-----------|
| `field=a,b,c` | String | `field IN (a, b, c)` |
| `field=a,b` | Numeric | `a ≤ field ≤ b` |
| `field=a,` | Numeric | `field ≥ a` |
| `field=,b` | Numeric | `field ≤ b` |

Projection filter params use the same `field=value` form as standard params. The projection itself is responsible for knowing which param names belong to it.

### Query execution flow

```
1. Phase 1 — events table query
   Apply: source, type, since, until, cursor, limit, order
   → event_ids[]

2. Phase 2 — projection secondary filter (if applicable)
   registry.filter(source, type, event_ids, projection_filters)
   → filtered event_ids[] (ordered subset, may be shorter than limit)

3. Fetch full event records for final event_ids
   → return events[]

Pagination: if result < limit, client continues with next cursor.
Rationale: projection queries are primarily used for statistics/aggregation,
not exhaustive pagination, so under-delivery is acceptable.
```

---

## Configuration (simplified)

Removed config keys: `WEBHOOK_MAX_RETRIES`, `WEBHOOK_RETRY_BACKOFF`, `S3_*` (all S3 variables).

Remaining config is unchanged.

---

## File Structure Changes

```
DELETE: app/webhooks.py (or equivalent webhook module)
DELETE: app/promoted.py
DELETE: app/schemas.py (schema registration logic)
DELETE: clients/ (entire directory)
MODIFY: app/models.py — remove EventTypeSchemaRecord, WebhookRecord, embedding field
MODIFY: app/store.py — remove webhook trigger, schema validation, promoted query
MODIFY: app/database.py — remove dynamic promoted table cache/creation
MODIFY: app/main.py — remove deleted endpoints, add projection registry wiring
ADD:    app/projections/__init__.py — BaseProjection + ProjectionRegistry
ADD:    app/projections/<name>.py — one file per concrete projection
ADD:    alembic/versions/<id>_add_proj_*.py — migration per projection table
```
