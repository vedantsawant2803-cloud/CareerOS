"""Application configuration loaded from environment variables and `.env` files.

Design goals:

* Every setting is declared once, with a safe default.
* Bad values produce clear validation errors instead of runtime surprises.
* Secrets are never rendered back to API responses (see ``api/routes.py``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    """Raised when the loaded configuration cannot be used safely."""


class Settings(BaseSettings):
    """Typed application settings sourced from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_env: str = Field(default="development", description="development|test|production")
    log_level: str = Field(default="INFO")

    # --- HTTP --------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = Field(default="/api/v1")
    allowed_origins: str = Field(default="*")
    api_key_enabled: bool = Field(default=False)
    api_key: str = Field(default="")

    # --- Frontend ----------------------------------------------------------
    frontend_port: int = Field(default=8501, ge=1, le=65535)
    backend_url: str = Field(default="http://localhost:8000")

    # --- Vector store ------------------------------------------------------
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="career_os")
    qdrant_api_key: str = Field(default="")

    # --- Embedding / reranking --------------------------------------------
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    reranker_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    enable_reranker: bool = Field(default=True)
    keyword_boost: float = Field(default=0.15, ge=0.0, le=1.0)

    # --- LLM (OpenAI-compatible endpoint; local by default) ----------------
    llm_provider: str = Field(default="ollama")
    llm_base_url: str = Field(default="http://127.0.0.1:11434/v1")
    llm_model: str = Field(default="llama3.1")
    llm_api_key: str = Field(default="")
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=1200, ge=64, le=8192)
    llm_timeout_seconds: int = Field(default=120, ge=1, le=600)

    # --- Retrieval / chunking ---------------------------------------------
    top_k_retrieval: int = Field(default=20, ge=1, le=200)
    top_n_reranked: int = Field(default=5, ge=1, le=50)
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    min_chunk_length: int = Field(default=80, ge=0, le=2000)

    # --- Input limits ------------------------------------------------------
    max_query_length: int = Field(default=2000, ge=50, le=50_000)
    max_job_description_length: int = Field(default=12000, ge=100, le=200_000)
    max_document_length: int = Field(default=100000, ge=1000, le=5_000_000)

    # --- Privacy / public demo --------------------------------------------
    public_profile_mode: bool = Field(default=True)
    show_contact_information: bool = Field(default=False)
    enable_debug_endpoints: bool = Field(default=False)

    # --- Public links ------------------------------------------------------
    github_url: str = Field(default="")
    linkedin_url: str = Field(default="")
    portfolio_url: str = Field(default="")

    # --- Paths -------------------------------------------------------------
    data_dir: str = Field(default="data/sample_docs")
    eval_file: str = Field(default="data/eval/questions.json")

    # --- Validators --------------------------------------------------------
    @field_validator("api_prefix")
    @classmethod
    def _api_prefix_must_be_absolute(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("API_PREFIX must start with '/', e.g. '/api/v1'")
        return value.rstrip("/") or "/api/v1"

    @field_validator("app_env")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        allowed = {"development", "test", "production", "staging"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"APP_ENV must be one of {sorted(allowed)}, got '{value}'")
        return normalized

    @field_validator(
        "qdrant_url",
        "llm_base_url",
        "backend_url",
        mode="before",
    )
    @classmethod
    def _strip_trailing_slash(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_smaller_than_chunk(cls, value: int, info) -> int:  # type: ignore[no-untyped-def]
        chunk_size = info.data.get("chunk_size")
        if isinstance(chunk_size, int) and value >= chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return value

    # --- Derived helpers ---------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def eval_path(self) -> Path:
        return Path(self.eval_file)

    @property
    def llm_api_key_effective(self) -> str:
        """Local OpenAI-compatible servers ignore auth but the SDK needs a value."""
        return self.llm_api_key or "not-needed"

    def validate_environment(self) -> None:
        """Fail fast with actionable messages when critical settings are unusable."""
        problems: list[str] = []
        if not self.qdrant_url.startswith(("http://", "https://")):
            problems.append("QDRANT_URL must start with http:// or https://")
        if not self.llm_base_url.startswith(("http://", "https://")):
            problems.append("LLM_BASE_URL must start with http:// or https://")
        if self.top_n_reranked > self.top_k_retrieval:
            problems.append("TOP_N_RERANKED cannot exceed TOP_K_RETRIEVAL")
        if self.is_production:
            if self.api_key_enabled and len(self.api_key) < 16:
                problems.append("API_KEY must be at least 16 characters when API_KEY_ENABLED=true")
            if self.allowed_origins.strip() == "*":
                problems.append(
                    "ALLOWED_ORIGINS must be restricted to explicit origins in production"
                )
            if self.enable_debug_endpoints:
                problems.append("ENABLE_DEBUG_ENDPOINTS must be false in production")
            if self.show_contact_information:
                problems.append("SHOW_CONTACT_INFORMATION must be false in public/production mode")
        if problems:
            raise SettingsError("CareerOS configuration is invalid:\n- " + "\n- ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object (cached)."""
    settings = Settings()  # pydantic raises ValidationError with clear field errors
    settings.validate_environment()
    return settings


def clear_settings_cache() -> None:
    """Used by tests to re-read environment variables."""
    get_settings.cache_clear()
