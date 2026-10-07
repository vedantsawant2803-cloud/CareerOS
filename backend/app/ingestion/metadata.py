"""Metadata extraction: technologies, years, citation fields, chunk descriptors."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.ingestion.models import Chunk, Document, Section
from app.utils.hashing import sha256_text, stable_chunk_id
from app.utils.text import extract_years

CANDIDATE_NAME = "Vedant Sawant"

# Ordered longest-first so "React Native" wins over "React".
KNOWN_TECHNOLOGIES: tuple[str, ...] = (
    "Data Structures and Algorithms",
    "GitHub REST API",
    "Object-Oriented Programming",
    "React Native",
    "Express.js",
    "REST APIs",
    "REST API",
    "Visual Studio Code",
    "Python microservices",
    "microservices",
    "MongoDB",
    "MySQL",
    "JavaScript",
    "TypeScript",
    "Postman",
    "Docker",
    "GitHub",
    "Git",
    "Expo",
    "Vite",
    "React",
    "Node.js",
    "Express",
    "Python",
    "HTML",
    "CSS",
    "SQL",
    "Telegram",
    "OTP",
    "AI",
)

_TECH_PATTERN = re.compile(
    "(" + "|".join(r"\b" + re.escape(tech) + r"\b" for tech in KNOWN_TECHNOLOGIES) + ")",
    re.IGNORECASE,
)
_TECH_CANONICAL = {tech.lower(): tech for tech in KNOWN_TECHNOLOGIES}


def detect_technologies(text: str) -> list[str]:
    """Return canonical technology names mentioned in ``text`` (deduplicated)."""
    found: list[str] = []
    for match in _TECH_PATTERN.finditer(text):
        canonical = _TECH_CANONICAL.get(match.group(1).lower())
        if canonical and canonical not in found:
            found.append(canonical)
    return found


def detect_year(text: str) -> int | None:
    """First plausible year mentioned in the text, if any."""
    years = extract_years(text)
    return years[0] if years else None


def utc_timestamp() -> str:
    """ISO-8601 UTC timestamp used for ``ingestion_timestamp``."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_chunk(
    document: Document,
    section: Section,
    text: str,
    index: int,
    ingestion_timestamp: str,
) -> Chunk:
    """Assemble a fully-described chunk ready for embedding and citation."""
    content_hash = sha256_text(text)
    chunk_id = stable_chunk_id(
        document_id=document.document_id,
        heading_path=section.heading_path,
        index=index,
        content_hash=content_hash,
    )
    return Chunk(
        chunk_id=chunk_id,
        document_id=document.document_id,
        text=text,
        source_file=document.source_file,
        document_type=document.document_type,
        title=document.title,
        section=section.title,
        heading_path=section.heading_path,
        candidate=CANDIDATE_NAME,
        technologies=detect_technologies(text),
        year=detect_year(text) or detect_year(document.text),
        content_hash=content_hash,
        ingestion_timestamp=ingestion_timestamp,
        index=index,
        metadata={
            "file_extension": document.metadata.get("file_extension", ""),
        },
    )


def describe_document(document: Document) -> dict[str, object]:
    """Public-facing description of a document (used by debug/inspection APIs)."""
    return {
        "document_id": document.document_id,
        "source_file": document.source_file,
        "title": document.title,
        "document_type": document.document_type,
        "content_hash": document.content_hash,
        "characters": len(document.text),
        "technologies": detect_technologies(document.text),
        "years": extract_years(document.text),
    }
