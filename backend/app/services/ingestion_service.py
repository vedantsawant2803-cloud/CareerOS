"""Ingestion service: thin wrapper around the index pipeline."""

from __future__ import annotations

import logging

from app.config import Settings
from app.ingestion.index_pipeline import IndexPipeline, IngestionError
from app.ingestion.models import IngestionResult
from app.services import BadRequestError, ServiceUnavailableError

logger = logging.getLogger(__name__)


class IngestionService:
    """Runs and reports on document indexing."""

    def __init__(self, settings: Settings, pipeline: IndexPipeline) -> None:
        self.settings = settings
        self.pipeline = pipeline

    def ingest(self, data_dir: str | None = None, reset: bool = False) -> IngestionResult:
        """Index documents from ``data_dir`` (defaults to the configured corpus)."""
        target = data_dir or self.settings.data_dir
        logger.info("Ingestion requested (data_dir=%s, reset=%s)", target, reset)
        try:
            return self.pipeline.run(data_dir=target, reset=reset)
        except IngestionError as exc:
            message = str(exc)
            if "not found" in message.lower() or "does not exist" in message.lower():
                raise BadRequestError(message) from exc
            raise ServiceUnavailableError(message) from exc
