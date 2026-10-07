"""Text helpers shared by ingestion, retrieval, and generation."""

from __future__ import annotations

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
MARKDOWN_BULLET_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return WHITESPACE_RE.sub(" ", text).strip()


def slugify(text: str, max_length: int = 48) -> str:
    """Turn a heading/path into a filesystem- and URL-safe slug."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug[:max_length].rstrip("-") or "section"


def is_bullet(line: str) -> bool:
    """True when a line is a Markdown list item."""
    return bool(MARKDOWN_BULLET_RE.match(line))


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, keeping bullet groups together."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.rstrip())
        elif current:
            blocks.append("\n".join(current).strip())
            current = []
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def first_sentence(text: str, max_length: int = 240) -> str:
    """Return a short quotable excerpt for citation cards."""
    compact = normalize_whitespace(text)
    if not compact:
        return ""
    match = SENTENCE_SPLIT_RE.split(compact)
    first = match[0].strip() if match else compact
    if len(first) <= max_length:
        return first
    truncated = first[: max_length - 1].rsplit(" ", 1)[0]
    return truncated + "…"


def truncate(text: str, max_length: int) -> str:
    """Hard truncation with an ellipsis marker."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def keyword_overlap_score(query: str, document: str) -> float:
    """Simple lexical overlap in [0, 1] used for optional keyword boosting."""
    query_terms = {t for t in re.findall(r"[a-z0-9.+]+", query.lower()) if len(t) > 1}
    if not query_terms:
        return 0.0
    doc_terms = set(re.findall(r"[a-z0-9.+]+", document.lower()))
    return len(query_terms & doc_terms) / len(query_terms)


def extract_years(text: str) -> list[int]:
    """Find 4-digit years in the plausible modern range."""
    years = {int(match) for match in re.findall(r"\b(20[0-4]\d)\b", text)}
    return sorted(years)
