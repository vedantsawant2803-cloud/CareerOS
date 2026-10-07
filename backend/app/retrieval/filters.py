"""Metadata filtering helpers.

Exact-match filters (``document_type``, ``technology``, ``year``) are pushed
down to Qdrant. The ``project`` filter is applied in-process after scoring so
that case- and phrasing-variations ("DevLens", "devlens", "Apartment Visitor
Security System") keep working without requiring a full-text payload index.
"""

from __future__ import annotations

from qdrant_client import models

from app.retrieval.qdrant_store import ScoredPoint
from app.utils.text import slugify


def build_qdrant_filter(
    project: str | None = None,
    document_type: str | None = None,
    technology: str | None = None,
    year: int | None = None,
) -> models.Filter | None:
    """Build a Qdrant filter from the supported exact-match facets.

    ``project`` is intentionally excluded here — see :func:`matches_project`.
    """
    del project  # handled client-side for robust matching
    conditions: list[models.Condition] = []
    if document_type:
        conditions.append(
            models.FieldCondition(
                key="document_type", match=models.MatchValue(value=document_type.strip().lower())
            )
        )
    if technology:
        conditions.append(
            models.FieldCondition(
                key="technologies", match=models.MatchValue(value=technology.strip())
            )
        )
    if year is not None:
        conditions.append(
            models.FieldCondition(key="year", match=models.MatchValue(value=int(year)))
        )
    if not conditions:
        return None
    return models.Filter(must=conditions)


def matches_project(payload: dict, project: str) -> bool:
    """True when a payload belongs to the requested project.

    Compares slugified titles, section titles, and source-file stems, so
    ``DevLens``, ``devlens`` and ``devlens.md`` all match.
    """
    wanted = slugify(project, max_length=64)
    if not wanted:
        return True
    candidates = {
        slugify(str(payload.get("title", "")), max_length=64),
        slugify(str(payload.get("source_file", "")).rsplit("/", 1)[-1], max_length=64),
        slugify(str(payload.get("source_file", "")), max_length=64),
        slugify(str(payload.get("heading_path", "")), max_length=64),
    }
    if wanted in candidates:
        return True
    return any(wanted in candidate or candidate in wanted for candidate in candidates if candidate)


def apply_project_filter(points: list[ScoredPoint], project: str | None) -> list[ScoredPoint]:
    """Keep only the points that belong to ``project`` (if requested)."""
    if not project:
        return points
    return [point for point in points if matches_project(point.payload, project)]
