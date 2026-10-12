"""
AutoFlow — FastAPI Application Entry Point
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from autoflow.core.config import get_settings
from autoflow.core.database import engine
from autoflow.core.logging import configure_logging, get_logger

# ─── Configure logging first ─────────────────────────────────────────────────
configure_logging()
logger = get_logger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:  # noqa: ARG001 - FastAPI lifespan signature
    """Startup and shutdown lifecycle management."""
    settings = get_settings()

    logger.info(
        "AutoFlow starting up",
        env=settings.app_env,
        version=settings.app_version,
        ai_provider=settings.ai_provider,
        ai_model=settings.resolved_ai_model,
    )

    # Startup: verify database connection
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception:
        logger.exception("Database connection failed — check DATABASE_URL")
        raise

    yield

    # Shutdown: dispose connection pool
    await engine.dispose()
    logger.info("AutoFlow shutdown complete")


# ─── App Factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="AutoFlow API",
        description=(
            "AutoFlow — AI Workflow Recorder & Automation Platform. "
            "Learn workflows by demonstration, not configuration."
        ),
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    # ─── Middleware ───────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ─── Routers ──────────────────────────────────────────
    from autoflow.ai.router import router as ai_router
    from autoflow.connectors.router import router as connectors_router
    from autoflow.recordings.router import router as recordings_router
    from autoflow.workflows.router import router as workflows_router

    prefix = settings.api_v1_prefix

    app.include_router(recordings_router, prefix=f"{prefix}/recordings", tags=["Recordings"])
    app.include_router(ai_router, prefix=f"{prefix}/ai", tags=["AI Planner"])
    app.include_router(workflows_router, prefix=f"{prefix}/workflows", tags=["Workflows"])
    app.include_router(connectors_router, prefix=f"{prefix}/connectors", tags=["Connectors"])

    # ─── System Endpoints ─────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health_check() -> JSONResponse:
        """Health check endpoint for Docker and load balancers."""
        return JSONResponse({
            "status": "healthy",
            "version": settings.app_version,
            "env": settings.app_env,
        })

    @app.get("/", tags=["System"])
    async def root() -> JSONResponse:
        return JSONResponse({
            "name": "AutoFlow API",
            "version": settings.app_version,
            "docs": "/docs",
            "message": "Demonstrate it once. AutoFlow handles it forever.",
        })

    return app


# ─── App Instance ─────────────────────────────────────────────────────────────
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "autoflow.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level="debug" if settings.is_development else "info",
    )
