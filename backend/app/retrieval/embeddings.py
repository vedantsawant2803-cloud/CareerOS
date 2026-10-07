"""Embedding provider.

The model is loaded lazily so that API startup and unit tests stay fast, and so
the vector dimension is **detected from the model** rather than hard-coded.

If ``sentence-transformers`` is not installed (or the model cannot be
downloaded), :meth:`EmbeddingProvider.available` reports ``False`` and callers
surface a clear 503-style message instead of an opaque traceback.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(RuntimeError):
    """Raised when embeddings cannot be produced (missing deps / model)."""


class EmbeddingProvider:
    """Lazy wrapper around a sentence-transformers model."""

    def __init__(self, model_name: str, device: str | None = None, batch_size: int = 32) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._dim: int | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @staticmethod
    def library_available() -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def available(self) -> bool:
        return self.library_available()

    def _load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingUnavailableError(
                    "sentence-transformers is not installed. "
                    "Install backend/requirements.txt to enable embeddings."
                ) from exc
            try:
                logger.info("Loading embedding model %s ...", self.model_name)
                self._model = SentenceTransformer(self.model_name, device=self.device)
                detected = self._model.get_sentence_embedding_dimension()
                self._dim = int(detected) if detected else None
                logger.info("Embedding model ready (dimension=%s)", self._dim)
            except Exception as exc:  # noqa: BLE001 - surface as domain error
                raise EmbeddingUnavailableError(
                    f"Failed to load embedding model '{self.model_name}': {exc}"
                ) from exc
            return self._model

    # ------------------------------------------------------------------
    @property
    def dimension(self) -> int:
        """Detected embedding dimension (never hard-coded)."""
        if self._dim is None:
            self._load()
        assert self._dim is not None
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        self._dim = int(vectors.shape[-1])
        return [[float(value) for value in row] for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]
