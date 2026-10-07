#!/usr/bin/env python3
"""Index source documents into the Qdrant vector store.

Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --data-dir data/sample_docs --reset

Run it inside the backend container with Docker:
    docker compose exec backend python scripts/seed_data.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (str(ROOT), str(ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover - python-dotenv is a runtime dependency
    pass

from app.config import Settings, SettingsError, get_settings  # noqa: E402
from app.ingestion.index_pipeline import IndexPipeline, IngestionError  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.retrieval.embeddings import EmbeddingProvider  # noqa: E402
from app.retrieval.qdrant_store import QdrantStore  # noqa: E402


def resolve_data_dir(value: str) -> Path:
    """Resolve a possibly relative path against the repo root first."""
    path = Path(value)
    if path.is_absolute():
        return path
    repo_candidate = ROOT / path
    if repo_candidate.exists():
        return repo_candidate
    return Path.cwd() / path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index CareerOS source documents.")
    parser.add_argument(
        "--data-dir",
        default="data/sample_docs",
        help="Directory containing Markdown/TXT/JSON/PDF sources (default: data/sample_docs)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the collection first and rebuild the index from scratch.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Override QDRANT_COLLECTION for this run.",
    )
    return parser.parse_args(argv)


def build_pipeline(settings: Settings) -> IndexPipeline:
    embedder = EmbeddingProvider(settings.embedding_model)
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        api_key=settings.qdrant_api_key or None,
    )
    return IndexPipeline(settings, embedder, store)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = get_settings()
        if args.collection:
            settings.qdrant_collection = args.collection
        settings.validate_environment()
    except SettingsError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pydantic ValidationError
        print(f"Invalid environment configuration: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings)
    data_dir = resolve_data_dir(args.data_dir)

    print(f"CareerOS seeding → collection '{settings.qdrant_collection}'")
    print(f"Data directory     : {data_dir}")
    print(f"Qdrant             : {settings.qdrant_url}")
    print(f"Embedding model    : {settings.embedding_model}")
    print(f"Reranker model     : {settings.reranker_model}")
    print("-" * 60)

    pipeline = build_pipeline(settings)
    try:
        result = pipeline.run(data_dir=data_dir, reset=args.reset)
    except IngestionError as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(result.as_printable())
    if result.indexed == 0:
        print("No chunks were indexed — check the data directory contents.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
