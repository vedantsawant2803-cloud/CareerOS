"""Health service: dependency checks for /health and readiness probes."""

from __future__ import annotations

import logging

from app import __version__
from app.config import Settings
from app.generation.generator import AnswerGenerator
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.qdrant_store import QdrantStore, QdrantStoreError
from app.retrieval.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)


class HealthService:
    """Aggregates liveness/readiness information without leaking secrets."""

    def __init__(
        self,
        settings: Settings,
        store: QdrantStore,
        embedder: EmbeddingProvider,
        reranker: CrossEncoderReranker | None,
        generator: AnswerGenerator,
    ) -> None:
        self.settings = settings
        self.store = store
        self.embedder = embedder
        self.reranker = reranker
        self.generator = generator

    def check(self) -> dict:
        qdrant_reachable = self.store.ping()
        points: int | None = None
        if qdrant_reachable:
            try:
                points = self.store.count()
            except QdrantStoreError:
                points = None

        checks = {
            "qdrant": {"reachable": qdrant_reachable, "collection_points": points},
            "embeddings": {
                "model": self.settings.embedding_model,
                "library_available": EmbeddingProvider.library_available(),
            },
            "reranker": {
                "model": self.settings.reranker_model,
                "enabled": bool(self.settings.enable_reranker),
                "available": bool(self.reranker and self.reranker.available),
            },
            "llm": {
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
                "base_url": self.settings.llm_base_url,
                "client_available": self.generator.available,
            },
        }

        ready = qdrant_reachable and checks["embeddings"]["library_available"]
        status = "ok" if ready else ("degraded" if qdrant_reachable else "unavailable")

        return {
            "status": status,
            "version": __version__,
            "environment": self.settings.app_env,
            "ready": ready,
            "checks": checks,
        }
