"""Dependency injection: one container of wired services per application.

Components are constructed cheaply at startup; heavy resources (embedding
model, reranker weights) load lazily on first use. Tests can replace
``app.state.container`` with a stub to run without Qdrant or an LLM.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request

from app.config import Settings, get_settings
from app.generation.generator import AnswerGenerator
from app.ingestion.index_pipeline import IndexPipeline
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.qdrant_store import QdrantStore
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.retriever import Retriever
from app.services.career_service import CareerService
from app.services.health_service import HealthService
from app.services.ingestion_service import IngestionService


class Container:
    """Application service container (composition root)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self.embedder = EmbeddingProvider(settings.embedding_model)
        self.store = QdrantStore(
            url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            api_key=settings.qdrant_api_key or None,
        )
        self.reranker = CrossEncoderReranker(
            model_name=settings.reranker_model,
            enabled=settings.enable_reranker,
        )
        self.retriever = Retriever(
            settings=settings,
            embedder=self.embedder,
            store=self.store,
            reranker=self.reranker,
        )
        self.generator = AnswerGenerator(settings)
        self.pipeline = IndexPipeline(settings, self.embedder, self.store)

        self.career_service = CareerService(settings, self.retriever, self.generator)
        self.ingestion_service = IngestionService(settings, self.pipeline)
        self.health_service = HealthService(
            settings=settings,
            store=self.store,
            embedder=self.embedder,
            reranker=self.reranker,
            generator=self.generator,
        )


def build_container(settings: Settings) -> Container:
    """Factory used by the app lifespan and by scripts."""
    return Container(settings)


# ----------------------------------------------------------------------------
# FastAPI dependencies
# ----------------------------------------------------------------------------
def get_settings_dep(request: Request) -> Settings:
    """Settings attached during app creation."""
    return getattr(request.app.state, "settings", None) or get_settings()


def get_container(request: Request) -> Container:
    """Service container attached during app creation."""
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - lifespan always sets it
        raise HTTPException(status_code=503, detail="Application container not initialised")
    return container


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Optional API-key guard.

    No-op unless ``API_KEY_ENABLED=true``. When enabled, every ``/api/v1``
    request must present a matching ``X-API-Key`` header.
    """
    settings = get_settings_dep(request)
    if not settings.api_key_enabled:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
