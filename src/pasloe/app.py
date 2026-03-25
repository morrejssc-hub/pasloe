from contextlib import asynccontextmanager
from fastapi import FastAPI

from .database import init_db, close_engine
from .api import router
from fastapi.responses import HTMLResponse
import os


# Application state for health checks
class AppState:
    def __init__(self):
        self.ready = False
        self.startup_error = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
        from .projections import ProjectionRegistry
        app.state.projection_registry = ProjectionRegistry([])
        from .config import get_settings
        if not get_settings().allow_insecure_http:
            print("\n" + "!" * 60)
            print("  SECURITY WARNING: Pasloe is running in secure mode.")
            print("  Ensure you are using HTTPS or set ALLOW_INSECURE_HTTP=True.")
            print("!" * 60 + "\n")
        app_state.ready = True
    except Exception as e:
        app_state.startup_error = str(e)
        app_state.ready = False
        raise
    
    try:
        yield
    finally:
        # Shutdown
        app_state.ready = False
        await close_engine()


app = FastAPI(
    title="Pasloe EventStore",
    description="Semantically-agnostic append-only event store with schema-driven data promotion.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    """
    Health check endpoint for container orchestration.
    
    Returns 200 when the application is ready to serve requests.
    Returns 503 during startup or if startup failed.
    """
    if not app_state.ready:
        from fastapi import HTTPException
        detail = {"status": "not_ready"}
        if app_state.startup_error:
            detail["error"] = app_state.startup_error
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ok"}


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui():
    ui_path = os.path.join(os.path.dirname(__file__), "ui.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()
