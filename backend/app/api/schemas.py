"""Pydantic request/response schemas — the API contract for CareerOS."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings
from app.generation.citations import Citation
from app.generation.prompts import SUPPORTED_MODES

JOB_REQUIRED_MODES = ("tailor_resume", "skill_gap")


class APIModel(BaseModel):
    """Base model: allow extra response fields for forward compatibility."""

    model_config = ConfigDict(extra="allow")


# ----------------------------------------------------------------------------
# Query
# ----------------------------------------------------------------------------
class Filters(BaseModel):
    """Optional metadata filters applied during retrieval."""

    project: str | None = None
    document_type: str | None = None
    technology: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)

    @field_validator("project", "document_type", "technology")
    @classmethod
    def _strip_blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class QueryRequest(BaseModel):
    """POST /api/v1/query request body."""

    query: str = Field(..., description="Natural-language question about the profile.")
    mode: str = Field(default="qa", description=f"One of {', '.join(SUPPORTED_MODES)}")
    job_description: str | None = Field(
        default=None,
        description="Required for tailor_resume and skill_gap modes.",
    )
    filters: Filters = Field(default_factory=Filters)
    include_debug: bool = Field(
        default=False,
        description="Include retrieved chunks for inspection when true.",
    )

    @field_validator("query")
    @classmethod
    def _query_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        return cleaned

    @field_validator("mode")
    @classmethod
    def _mode_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_MODES:
            raise ValueError(
                f"Unsupported mode '{value}'. Supported modes: {', '.join(SUPPORTED_MODES)}"
            )
        return normalized

    @model_validator(mode="after")
    def _length_and_job_description_rules(self) -> QueryRequest:
        settings = get_settings()
        if len(self.query) > settings.max_query_length:
            raise ValueError(
                f"query exceeds MAX_QUERY_LENGTH ({len(self.query)} > {settings.max_query_length})"
            )
        if self.job_description is not None:
            self.job_description = self.job_description.strip() or None
            if self.job_description and len(self.job_description) > (
                settings.max_job_description_length
            ):
                raise ValueError(
                    "job_description exceeds MAX_JOB_DESCRIPTION_LENGTH ("
                    f"{len(self.job_description)} > {settings.max_job_description_length})"
                )
        if self.mode in JOB_REQUIRED_MODES and not self.job_description:
            raise ValueError(f"mode='{self.mode}' requires a non-empty 'job_description'")
        return self


class RetrievedChunkView(BaseModel):
    """Debug view of a retrieved chunk (only returned with include_debug)."""

    rank: int
    chunk_id: str
    text: str
    source_file: str
    title: str
    section: str
    document_type: str
    technologies: list[str] = Field(default_factory=list)
    year: int | None = None
    vector_score: float = 0.0
    rerank_score: float | None = None


class QueryMetadata(APIModel):
    """Response metadata for a query."""

    retrieval_count: int
    latency_ms: float
    llm_model: str
    confidence: str
    used_llm: bool = False
    citation_coverage: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """POST /api/v1/query response body."""

    answer: str
    mode: str
    citations: list[Citation] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunkView] = Field(default_factory=list)
    metadata: QueryMetadata


# ----------------------------------------------------------------------------
# Ingestion
# ----------------------------------------------------------------------------
class IngestRequest(BaseModel):
    """POST /api/v1/ingest request body."""

    data_dir: str = Field(default="data/sample_docs", description="Relative path to documents")
    reset: bool = Field(default=False, description="Drop and rebuild the collection")

    @field_validator("data_dir")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        from pathlib import Path

        cleaned = value.strip() or "data/sample_docs"
        path = Path(cleaned)
        has_drive = bool(cleaned[:1].isalpha() and ":" in cleaned[:3])
        is_root_relative = cleaned.startswith(("/", "\\")) or has_drive
        if path.is_absolute() or is_root_relative or ".." in path.parts:
            raise ValueError(
                "data_dir must be a relative path inside the workspace "
                "(absolute paths and '..' are not allowed)"
            )
        return cleaned


class IngestResponse(BaseModel):
    """POST /api/v1/ingest response body."""

    documents: int
    chunks: int
    indexed: int
    skipped: int = 0
    collection: str
    embedding_model: str
    reranker_model: str
    data_dir: str
    reset: bool
    warnings: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------
# Profile / projects
# ----------------------------------------------------------------------------
class ContactInfo(BaseModel):
    email: str
    phone: str


class ProfileLinks(BaseModel):
    github: str = ""
    linkedin: str = ""
    portfolio: str = ""


class ProfileSource(BaseModel):
    source_file: str
    section: str = ""


class ProfileResponse(APIModel):
    """GET /api/v1/profile — contact details only when explicitly enabled."""

    name: str
    title: str
    location: str = ""
    summary: str = ""
    education: list[dict[str, Any]] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    engineering_strengths: list[str] = Field(default_factory=list)
    current_learning: list[str] = Field(default_factory=list)
    contact: ContactInfo | None = None
    links: ProfileLinks = Field(default_factory=ProfileLinks)
    public_profile_mode: bool = True
    sources: list[ProfileSource] = Field(default_factory=list)


class ProjectCitation(BaseModel):
    source_file: str
    document_type: str
    title: str
    section: str
    quote: str


class ProjectCard(BaseModel):
    """GET /api/v1/projects item."""

    name: str
    subtitle: str = ""
    document_type: str = "project"
    source_file: str
    technologies: list[str] = Field(default_factory=list)
    description: str = ""
    engineering_themes: list[str] = Field(default_factory=list)
    citation: ProjectCitation


# ----------------------------------------------------------------------------
# Health / config
# ----------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """GET /health response body."""

    status: str
    version: str
    environment: str
    ready: bool
    checks: dict[str, Any] = Field(default_factory=dict)


class ConfigStatus(BaseModel):
    """GET /api/v1/config/status — never contains secret values."""

    version: str
    app_env: str
    log_level: str
    api_prefix: str
    qdrant_url: str
    qdrant_collection: str
    embedding_model: str
    reranker_model: str
    reranker_enabled: bool
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key_configured: bool
    llm_temperature: float
    llm_max_tokens: int
    top_k_retrieval: int
    top_n_reranked: int
    chunk_size: int
    chunk_overlap: int
    min_chunk_length: int
    max_query_length: int
    max_job_description_length: int
    max_document_length: int
    api_key_enabled: bool
    debug_endpoints_enabled: bool
    public_profile_mode: bool
    show_contact_information: bool
    allowed_origins: list[str]
    links: ProfileLinks = Field(default_factory=ProfileLinks)


class ErrorBody(BaseModel):
    """Standard error envelope."""

    detail: str
    type: str = "error"
