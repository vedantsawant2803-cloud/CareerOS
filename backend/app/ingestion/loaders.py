"""Document loaders for Markdown, TXT, JSON, and (optional) PDF files.

Every loader returns a :class:`~app.ingestion.models.Document` with a
deterministic ``document_id`` so re-indexing can replace stale vectors safely.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.ingestion.models import Document
from app.utils.hashing import sha256_text, stable_document_id

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".pdf"}

# Exact sample-file shortcuts; filename/content heuristics act as fallbacks.
KNOWN_DOCUMENT_TYPES: dict[str, str] = {
    "vedant_resume.md": "resume",
    "devlens.md": "project",
    "enviromonitor.md": "project",
    "apartment_visitor_security.md": "project",
    "gdg_hackathon.md": "hackathon",
    "sies_hackathon.md": "hackathon",
    "linkedin_summary.md": "profile",
}

DEFAULT_TITLE_FALLBACK = "Untitled document"


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse a small YAML-like key: value front matter block if present."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    body_start = len(lines)
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped in {"---", "..."}:
            body_start = index + 1
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            metadata[key.strip().lower()] = value.strip().strip("'\"")
    body = "\n".join(lines[body_start:]).lstrip("\n")
    return metadata, body


def extract_title(text: str, fallback: str) -> str:
    """First `# ` heading, else the first non-empty line, else the file stem."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:120]
    return fallback


def detect_document_type(source_file: str, text: str, front_matter: dict[str, str]) -> str:
    """Detect the document type used for filtering and citation labels."""
    if front_matter.get("document_type"):
        return front_matter["document_type"].strip().lower()

    name = Path(source_file).name.lower()
    if name in KNOWN_DOCUMENT_TYPES:
        return KNOWN_DOCUMENT_TYPES[name]
    if "hackathon" in name:
        return "hackathon"
    if "resume" in name or name.startswith("cv"):
        return "resume"
    if "linkedin" in name or "profile" in name:
        return "profile"

    lowered = text.lower()
    if "## technologies" in lowered and ("## overview" in lowered or "## features" in lowered):
        return "project"
    return "document"


def _load_markdown_or_text(path: Path) -> tuple[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".md", ".markdown"}:
        front_matter, body = _parse_front_matter(text)
        return body, front_matter
    return text, {}


def _load_json(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("content"), str):
        front_matter = {
            key: str(value)
            for key, value in payload.items()
            if isinstance(value, (str, int, float))
        }
        return payload["content"], front_matter
    pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    return pretty, {}


def _load_pdf(path: Path) -> tuple[str, dict[str, str]]:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError as exc:  # pragma: no cover - exercised only when missing
        raise RuntimeError(
            "PDF support requires 'pypdf'. Install it with: pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n\n".join(pages), {}


def load_file(path: Path, root: Path | None = None) -> Document | None:
    """Load one supported file into a :class:`Document`.

    Raises ``ValueError`` for unreadable content so callers can skip with a
    warning instead of failing the entire run.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return None

    relative = path.relative_to(root) if root else path
    source_file = str(relative).replace("\\", "/")

    try:
        if suffix == ".json":
            body, front_matter = _load_json(path)
        elif suffix == ".pdf":
            body, front_matter = _load_pdf(path)
        else:
            body, front_matter = _load_markdown_or_text(path)
    except (ValueError, RuntimeError) as exc:
        logger.warning("Skipping %s: %s", source_file, exc)
        raise

    body = body.strip()
    if not body:
        logger.warning("Skipping empty file: %s", source_file)
        return None

    title = front_matter.get("title") or extract_title(body, path.stem.replace("_", " ").title())
    document_type = detect_document_type(source_file, body, front_matter)

    return Document(
        document_id=stable_document_id(source_file),
        source_file=source_file,
        title=title,
        document_type=document_type,
        text=body,
        content_hash=sha256_text(body),
        metadata={
            "file_name": path.name,
            "file_extension": suffix,
            "file_size_bytes": path.stat().st_size,
            **front_matter,
        },
    )


def load_documents(data_dir: str | Path) -> tuple[list[Document], list[str]]:
    """Recursively load all supported documents from ``data_dir``.

    Returns ``(documents, warnings)``; unreadable files become warnings so a
    single bad file never blocks indexing.
    """
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(
            f"Data directory not found: {root}. "
            "Expected Markdown sources such as data/sample_docs/."
        )

    documents: list[Document] = []
    warnings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            document = load_file(path, root=root)
        except (ValueError, RuntimeError) as exc:
            warnings.append(str(exc))
            continue
        if document is not None:
            documents.append(document)

    documents.sort(key=lambda doc: doc.source_file)
    if not documents:
        warnings.append(f"No supported documents found in {root}")
    return documents, warnings
