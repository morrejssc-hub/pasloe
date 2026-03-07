# Pasloe

Pasloe is a lightweight, high-performance, and append-only event store service designed for the Palimpsest system. It serves as a centralized hub for streaming events, managing data sources, and triggering real-time webhooks.

## Key Features

- **Append-Only Event Stream**: Robust storage for system events using SQLite or PostgreSQL.
- **Modern WebUI**: A beautiful, built-in dashboard for managing webhooks and monitoring sources/events.
- **Webhook Integration**: Asynchronous, fire-and-forget delivery of events to external services.
- **Cursor-Based Pagination**: Efficient event querying using `X-Next-Cursor` for large datasets.
- **S3 Artifact Support**: Integrated API for generating S3 presigned URLs, enabling secure client-side uploads.
- **Multi-Client Support**: Seamlessly integrates with Rust, Python, and other clients via REST API.

---

## 🚀 Quick Start

### 1. Requirements

- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Python 3.10+

### 2. Configuration

Set up your environment variables:

```bash
cp .env.example .env
# Edit .env to set your API_KEY, DATABASE_URL, and S3 credentials
```

### 3. Run the Server

```bash
uv sync
uv run uvicorn src.pasloe.app:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🖥️ Web Management UI

Pasloe includes a built-in dashboard accessible at:

**`http://localhost:8000/ui`**

Features:
- **Webhooks**: Register callbacks, manage event filters, and view subscription status.
- **Sources**: Monitor registered data sources and their metadata.
- **Events**: Real-time inspection of the event stream with JSON payload formatting.

---

## 📡 API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ui` | `GET` | Access the Web Management Dashboard |
| `/events` | `GET` | Query events with cursor pagination and filtering |
| `/events` | `POST` | Append a new event to the stream |
| `/sources` | `GET` | List all registered data sources |
| `/webhooks` | `GET` | List active webhook subscriptions |
| `/webhooks` | `POST` | Register a new webhook callback |
| `/artifacts/presign` | `POST` | Generate an S3 presigned URL for secure uploads |

**Authentication**: Include `X-API-Key: <your_key>` in the headers for all requests.

---

## 📦 Clients

- **[pasloe-screenshot](clients/pasloe-screenshot)**: A Rust-based desktop client that captures screenshots, deduplicates images using dHash, and streams them to Pasloe.

---

## 🛠️ Development

Run tests with `pytest`:

```bash
uv run pytest
```
