from contextlib import asynccontextmanager
from fastapi import FastAPI

from .database import init_db, close_engine
from .api import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        yield
    finally:
        await close_engine()


app = FastAPI(
    title="Palimpsest EventStore",
    description="Append-only event stream for the Palimpsest agent system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
