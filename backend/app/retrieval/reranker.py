"""Optional cross-encoder reranker.

Reranking is a quality enhancement, not a hard dependency: when the model or
library is unavailable the retriever falls back to vector scores, records a
warning, and keeps serving answers.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class RerankerUnavailableError(RuntimeError):
    """Raised when reranking was requested but cannot be performed."""


class CrossEncoderReranker:
    """Lazy wrapper around ``sentence_transformers.CrossEncoder``."""

    def __init__(self, model_name: str, enabled: bool = True) -> None:
        self.model_name = model_name
        self.enabled = enabled
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def library_available() -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.library_available())

    def _load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import CrossEncoder

            try:
                logger.info("Loading reranker model %s ...", self.model_name)
                self._model = CrossEncoder(self.model_name)
            except Exception as exc:  # noqa: BLE001
                raise RerankerUnavailableError(
                    f"Failed to load reranker '{self.model_name}': {exc}"
                ) from exc
            return self._model

    def score(self, query: str, texts: list[str]) -> list[float]:
        """Return one relevance score per text (higher is better)."""
        if not texts:
            return []
        model = self._load()
        pairs = [(query, text) for text in texts]
        raw = model.predict(pairs)
        return [float(value) for value in raw]
