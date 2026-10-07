"""FastAPI application factory and process entrypoint.

Run locally (without Docker):

    cd backend
    uvicorn app.main:app --reload --port 8000

Docker runs the same command via backend/Dockerfile.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.error_handlers import register_error_handlers
from app.api.routes import api_router, health_router
from app.config import Settings, SettingsError, get_settings
from app.dependencies import build_container
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    container: object | None = None,
) -> FastAPI:
    """Build the FastAPI application (used by tests and by the module-level app).

    ``container`` lets tests inject fakes so no live Qdrant/LLM is required.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    if settings.enable_debug_endpoints:
        logger.warning("Debug endpoints are ENABLED — do not use in production.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_environment()
        app.state.settings = settings
        app.state.container = container or build_container(settings)
        logger.info(
            "CareerOS %s started (env=%s, collection=%s, llm=%s@%s)",
            __version__,
            settings.app_env,
            settings.qdrant_collection,
            settings.llm_model,
            settings.llm_base_url,
        )
        yield
        logger.info("CareerOS shutting down")

    app = FastAPI(
        title="CareerOS API",
        description=(
            "Citation-grounded RAG assistant for exploring Vedant Sawant's projects, "
            "technical skills, hackathon experience, and software engineering profile."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    register_error_handlers(app, settings)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "service": "CareerOS",
            "version": __version__,
            "tagline": (
                "A citation-grounded AI assistant for exploring Vedant Sawant's projects, "
                "technical skills, hackathon experience, and software engineering profile."
            ),
            "api_prefix": settings.api_prefix,
            "docs": "/docs",
            "health": "/health",
        }

    return app


try:
    app = create_app()
except SettingsError:
    # Surface configuration problems clearly when run as an entrypoint.
    raise
