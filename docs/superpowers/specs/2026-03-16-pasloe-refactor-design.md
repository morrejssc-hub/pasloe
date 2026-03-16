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

### `sources`

```
id            String, PK  (user-defined)
metadata      JSON
registered_at DateTime with TZ
```

**Auto-registration:** `POST /events` with an unknown `source_id` silently creates the source with empty metadata. Explicit `POST /sources` functions as an upsert: returns `201` for a new source, `200` for an existing one (including auto-created). No `409` is ever returned — a second registration simply updates metadata.

---

## Projection System

Projections are code-defined acceleration tables for known, high-frequency event types. They are **purely additive**: events are always stored in the `events` table regardless of projection outcome. Projection writes are best-effort side effects.

### POST /events Response Model

`POST /events` always returns HTTP `201` with a body containing all standard event fields plus an optional `warnings` list:

```json
{
  "id": "...",
  "source_id": "...",
  "type": "...",
  "ts": "...",
  "data": { ... },
  "warnings": []
}
```

`warnings` is always present (empty list when no issues). `POST /events` uses a dedicated `EventCreatedResponse` model that extends the five core event fields (`id`, `source_id`, `type`, `ts`, `data`) with `warnings: list[str] = []`. The base `Event` model is unchanged and is used by `GET /events` (which never includes `warnings`).

### Validation Rules

When an event's `(source_id, type)` matches a registered projection:

- **Missing field** (projection column not present in `event.data`) → write `NULL` to that column
- **Extra field** (key in `event.data` not present in projection columns) → projection write is **skipped**; event is still committed; registry formats and appends to `warnings`, e.g.:
  ```
  "projection skipped: unknown fields: [region, tenant]"
  ```

Events with no matching projection are always accepted without any field-level validation.

### BaseProjection Interface

```python
class BaseProjection:
    __tablename__: str  # name of the projection's SQLAlchemy table
    source: str         # matched source_id
    event_type: str     # matched event type
    # Registry matches by comparing source and event_type attributes directly.

    async def on_insert(self, session, event: EventRecord) -> list[str]
    # Writes projection fields from event.data to the projection table.
    # - Missing projection field → write NULL
    # - Extra field in event.data not in projection columns → do NOT write;
    #   return the list of extra field names (registry formats the warning).
    # Returns empty list on clean success.

    async def filter(
        self,
        session,
        event_ids: list[UUID],  # ordered by ts|id from Phase 1
        filters: dict[str, str], # raw query-string values, e.g. {"model": "gpt-4,gpt-3.5", "cost": "0.01,"}
    ) -> list[UUID]
    # Each projection is responsible for parsing its own filter values:
    #   - String column: split on "," → IN list
    #   - Numeric column: split on "," → (lower, upper), either may be empty string → open bound
    # Returns a subset of event_ids preserving the original input order.
    # If filters contain no recognized projection fields, returns event_ids unchanged.
    # Implementation must preserve input order (e.g. ORDER BY array_position in Postgres,
    # or index-based reorder in Python).
```

### Projection Column Naming Constraint

Projection column names must not collide with the reserved standard query params:
`id`, `source`, `type`, `since`, `until`, `cursor`, `limit`, `order`.

### ProjectionRegistry

Automatically discovers all `BaseProjection` subclasses at startup by inspecting the `src/pasloe/projections/` package.

```python
# Event write path (called once per event insert, after event is committed)
warnings = await registry.on_event(session, event)
# Returns list[str] of formatted warning strings (empty if all projections succeeded).
# Registry formats raw field names from on_insert() into:
#   "projection skipped: unknown fields: [f1, f2]"

# Query path
filtered_ids = await registry.filter(source, event_type, event_ids, filters)
# - If source or event_type is None: returns event_ids unchanged (no projection targeting)
# - If no projection matches (source, event_type): returns event_ids unchanged
# - If projection matches: returns ordered filtered subset
```

Adding a new projection requires only:
1. Define a new `BaseProjection` subclass in `src/pasloe/projections/<name>.py`
2. Write an Alembic migration for its table
3. No changes to main application code

### Projection Table Lifecycle

- **Create:** Alembic migration adds the table
- **Populate:** `on_insert` writes new matching events going forward from deployment
- **Destructive change:** Write a new Alembic migration (alter or drop+recreate). Old projection data is lost; raw events remain intact and queryable. No backfill — projection accumulates from new events only.

### Example Projection

```python
class LLMCallProjection(BaseProjection):
    __tablename__ = "proj_llm_call"
    source = "agent"
    event_type = "llm_call"

    # SQLAlchemy columns — Alembic manages DDL for both SQLite and PostgreSQL
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

### Standard filters (events table, reserved param names)

| Param | Description |
|-------|-------------|
| `id=<uuid>` | Fetch single event by ID; projection filters are ignored when this is present |
| `source=<str>` | Filter by source_id |
| `type=<str>` | Filter by event type |
| `since=<iso>` | Events at or after timestamp |
| `until=<iso>` | Events before or at timestamp |
| `cursor=<str>` | Pagination cursor (`ts\|uuid` format) |
| `limit=<int>` | Max results (1–1000, default 100) |
| `order=asc\|desc` | Sort order (default asc) |

### Projection filters (ignored if no matching projection or if `id` is present)

| Syntax | Column type | Semantics |
|--------|-------------|-----------|
| `field=a,b,c` | String | `field IN (a, b, c)` |
| `field=a,b` | Numeric | `a ≤ field ≤ b` |
| `field=a,` | Numeric | `field ≥ a` |
| `field=,b` | Numeric | `field ≤ b` |

Any query param not in the reserved list above is treated as a candidate projection filter and passed to the matching projection's `filter()` method. Unknown params with no matching projection are silently ignored.

### Query execution flow

```
Special case — id= present:
  Fetch the single event by id; ignore cursor/limit/order/projection filters.
  Return it directly (no next_cursor in response).

Normal flow:
1. Phase 1 — events table query
   Apply: source, type, since, until, cursor, limit, order
   → event_ids[] ordered by (ts, id)
   → next_cursor = ts|id of the last event in this page (present whenever
     Phase 1 returned exactly `limit` results, regardless of Phase 2 outcome)

2. Phase 2 — projection secondary filter (if applicable)
   Condition: source AND type are both specified, and a projection matches
   registry.filter(source, type, event_ids, projection_filters)
   → filtered event_ids[] — ordered subset (preserving Phase 1 order)
   → may be shorter than limit; this is acceptable

3. Fetch full event records for final event_ids
   → return events[] (core event fields only: id, source_id, type, ts, data)

Response includes next_cursor in header X-Next-Cursor (unchanged from current).
next_cursor is present iff Phase 1 returned exactly `limit` results.
Under-delivery after Phase 2 is acceptable; clients use next_cursor to continue.
Projection queries are primarily for statistics/aggregation, not exhaustive iteration.
```

### GET /events/stats

Stats aggregate the `events` table directly. Projection filters are **not** applied to stats queries — `GET /events/stats` ignores any non-standard query params.

---

## Configuration (simplified)

Removed keys: `WEBHOOK_MAX_RETRIES`, `WEBHOOK_RETRY_BACKOFF`, all `S3_*` variables.

Remaining config is unchanged.

---

## File Structure Changes

All paths relative to repo root. The Python package lives at `src/pasloe/`.

```
DELETE: src/pasloe/webhooks.py (or equivalent webhook module)
DELETE: src/pasloe/promoted.py
DELETE: clients/ (entire directory)
MODIFY: src/pasloe/models.py — remove EventTypeSchemaRecord, WebhookRecord, embedding field;
                                add warnings: list[str] = [] to Event response model
MODIFY: src/pasloe/store.py — remove webhook trigger, schema validation, promoted query logic
MODIFY: src/pasloe/database.py — remove dynamic promoted table cache and creation logic
MODIFY: src/pasloe/main.py — remove deleted endpoints, wire ProjectionRegistry
ADD:    src/pasloe/projections/__init__.py — BaseProjection + ProjectionRegistry
ADD:    src/pasloe/projections/<name>.py — one file per concrete projection
ADD:    alembic.ini — Alembic configuration (supports SQLite and PostgreSQL)
ADD:    alembic/env.py — Alembic environment (reads DB_TYPE from app config)
ADD:    alembic/versions/<id>_add_proj_<name>.py — one migration per projection table
```
