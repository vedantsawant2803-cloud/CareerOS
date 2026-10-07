"""Shared pytest fixtures.

Tests run entirely offline: no Qdrant instance, no LLM, and no downloaded
sentence-transformers models. Heavy components are replaced with deterministic
fakes, and the API is exercised through FastAPI's TestClient.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

# --- Environment must be configured before importing the app ----------------
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ENABLE_RERANKER"] = "false"
os.environ["API_KEY_ENABLED"] = "false"
os.environ["SHOW_CONTACT_INFORMATION"] = "false"
os.environ["ENABLE_DEBUG_ENDPOINTS"] = "false"
# Absolute paths keep tests independent of the current working directory.
os.environ["DATA_DIR"] = str(_ROOT / "data" / "sample_docs")
os.environ["EVAL_FILE"] = str(_ROOT / "data" / "eval" / "questions.json")
# Instant connection refusal (port 9) keeps failure paths fast and offline.
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["LLM_TIMEOUT_SECONDS"] = "1"
os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"

import pytest  # noqa: E402
from app.config import Settings, clear_settings_cache  # noqa: E402
from app.dependencies import build_container  # noqa: E402
from app.generation.generator import GenerationResult  # noqa: E402
from app.ingestion.index_pipeline import IndexPipeline  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.qdrant_store import ScoredPoint  # noqa: E402
from app.retrieval.retriever import Retriever  # noqa: E402
from app.services.career_service import CareerService  # noqa: E402
from app.services.health_service import HealthService  # noqa: E402
from app.services.ingestion_service import IngestionService  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

clear_settings_cache()


# ----------------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic bag-of-words embedder (no ML dependencies)."""

    def __init__(self, dimension: int = 64) -> None:
        self.model_name = "fake-bow-embedder"
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def available(self) -> bool:
        return True

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in re.findall(r"[a-z0-9.+]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self._dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeStore:
    """In-memory vector store with the same surface as QdrantStore."""

    def __init__(self, url: str = "http://fake:6333", collection: str = "career_os") -> None:
        self.url = url
        self.collection = collection
        self.dimension: int | None = None
        self.points: list[tuple[list[float], dict]] = []

    def ping(self) -> bool:
        return True

    def collection_exists(self) -> bool:
        return self.dimension is not None

    def ensure_collection(self, dimension: int) -> None:
        if self.dimension is None:
            self.dimension = dimension
        elif self.dimension != dimension:
            raise RuntimeError("dimension mismatch")

    def reset(self) -> None:
        self.points = []

    def delete_document_ids(self, document_ids: list[str]) -> None:
        wanted = set(document_ids)
        self.points = [point for point in self.points if point[1].get("document_id") not in wanted]

    def upsert(self, chunks, vectors, batch_size: int = 64) -> int:  # type: ignore[no-untyped-def]
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.points.append((list(vector), chunk.payload()))
        return len(chunks)

    @staticmethod
    def _matches(payload: dict, qdrant_filter) -> bool:  # type: ignore[no-untyped-def]
        if qdrant_filter is None:
            return True
        for condition in getattr(qdrant_filter, "must", []) or []:
            key = getattr(condition, "key", None)
            match = getattr(condition, "match", None)
            value = getattr(match, "value", None)
            if key is None:
                continue
            payload_value = payload.get(key)
            if isinstance(payload_value, list):
                if value not in payload_value:
                    return False
            elif payload_value != value:
                return False
        return True

    def search(self, vector, limit: int, qdrant_filter=None) -> list[ScoredPoint]:  # type: ignore[no-untyped-def]
        scored: list[ScoredPoint] = []
        for point_vector, payload in self.points:
            if not self._matches(payload, qdrant_filter):
                continue
            dot = sum(a * b for a, b in zip(vector, point_vector, strict=False))
            scored.append(
                ScoredPoint(
                    id=str(payload.get("chunk_id", len(scored))),
                    score=float(dot),
                    payload=dict(payload),
                )
            )
        scored.sort(key=lambda point: point.score, reverse=True)
        return scored[:limit]

    def count(self) -> int:
        return len(self.points)


class StubGenerator:
    """Deterministic answer generator used by API tests."""

    def __init__(self, answer: str = "Stub grounded answer with citation [1].") -> None:
        self.answer = answer
        self.model_name = "stub-model"
        self.available = True

    def generate(
        self,
        mode: str,
        query: str,
        chunks,  # type: ignore[no-untyped-def]
        job_description: str | None = None,
    ) -> GenerationResult:
        if not chunks:
            return GenerationResult(
                answer=(
                    "The indexed profile does not contain enough information "
                    "to answer that accurately."
                ),
                llm_model=self.model_name,
                used_llm=False,
                warnings=["no chunks"],
            )
        markers = " ".join(f"[{index}]" for index in range(1, min(len(chunks), 3) + 1))
        return GenerationResult(
            answer=f"{self.answer} {markers}",
            llm_model=self.model_name,
            used_llm=True,
            warnings=[],
        )


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
@pytest.fixture
def settings() -> Settings:
    clear_settings_cache()
    return Settings(_env_file=None)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def offline_pipeline(settings: Settings):
    """An IndexPipeline wired to offline fakes: returns (pipeline, store)."""
    embedder = FakeEmbedder()
    store = FakeStore()
    return IndexPipeline(settings, embedder, store), store


@pytest.fixture
def test_container(settings: Settings, fake_embedder: FakeEmbedder, fake_store: FakeStore):
    """A fully wired container with offline fakes for embeddings/store/LLM."""
    container = build_container(settings)
    container.embedder = fake_embedder
    container.store = fake_store
    container.reranker = None
    container.retriever = Retriever(
        settings=settings,
        embedder=fake_embedder,
        store=fake_store,
        reranker=None,
    )
    container.generator = StubGenerator()
    container.pipeline = IndexPipeline(settings, fake_embedder, fake_store)
    container.career_service = CareerService(settings, container.retriever, container.generator)
    container.ingestion_service = IngestionService(settings, container.pipeline)
    container.health_service = HealthService(
        settings=settings,
        store=fake_store,
        embedder=fake_embedder,
        reranker=None,
        generator=container.generator,  # type: ignore[arg-type]
    )
    return container


@pytest.fixture
def app(settings: Settings, test_container: Any):
    return create_app(settings=settings, container=test_container)


@pytest.fixture
def client(app):  # type: ignore[no-untyped-def]
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_corpus(tmp_path) -> Any:
    """Small Markdown corpus for ingestion tests."""
    (tmp_path / "sample_project.md").write_text(
        "# Sample Project\n\n"
        "**A test project**\n\n"
        "## Overview\n\n"
        "A backend service built with Node.js and Express that exposes REST APIs.\n\n"
        "## Technologies\n\n"
        "- Node.js\n- Express\n- MySQL\n\n"
        "## Notes\n\n" + ("Detail line about testing and reliability. " * 40) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "sample_resume.md").write_text(
        "# Sample Resume\n\n"
        "**Student**\n\n"
        "## Professional Profile\n\n"
        "Computer Engineering student with security-focused development experience.\n\n"
        "## Technical Skills\n\n"
        "- **Languages:** JavaScript, Python\n"
        "- **Currently learning:** Data Structures and Algorithms\n",
        encoding="utf-8",
    )
    return tmp_path
