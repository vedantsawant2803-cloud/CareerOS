"""API routes.

All ``/api/v1`` routes sit behind the optional API-key dependency; ``/health``
stays open so orchestrators can probe liveness without credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app import __version__
from app.api.schemas import (
    ConfigStatus,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    ProfileResponse,
    ProjectCard,
    QueryRequest,
    QueryResponse,
)
from app.config import Settings
from app.dependencies import get_container, get_settings_dep, require_api_key
from app.services.career_service import CareerService
from app.services.health_service import HealthService
from app.services.ingestion_service import IngestionService

health_router = APIRouter(tags=["health"])
api_router = APIRouter(dependencies=[Depends(require_api_key)])


@health_router.get("/health", response_model=HealthResponse, summary="Liveness/readiness")
def health(request: Request, settings: Settings = Depends(get_settings_dep)) -> HealthResponse:
    container = get_container(request)
    health_service: HealthService = container.health_service
    return HealthResponse(**health_service.check())


@api_router.post("/query", response_model=QueryResponse, summary="Answer a profile question")
def query(payload: QueryRequest, request: Request) -> QueryResponse:
    container = get_container(request)
    career: CareerService = container.career_service
    result = career.answer_query(
        query=payload.query,
        mode=payload.mode,
        job_description=payload.job_description,
        project=payload.filters.project,
        document_type=payload.filters.document_type,
        technology=payload.filters.technology,
        year=payload.filters.year,
        include_debug=payload.include_debug,
    )
    return QueryResponse(**result)


@api_router.post("/ingest", response_model=IngestResponse, summary="Index source documents")
def ingest(payload: IngestRequest, request: Request) -> IngestResponse:
    container = get_container(request)
    service: IngestionService = container.ingestion_service
    result = service.ingest(data_dir=payload.data_dir, reset=payload.reset)
    return IngestResponse(**result.model_dump())


@api_router.get("/profile", response_model=ProfileResponse, summary="Structured public profile")
def profile(request: Request) -> ProfileResponse:
    container = get_container(request)
    career: CareerService = container.career_service
    return ProfileResponse(**career.get_profile())


@api_router.get("/projects", response_model=list[ProjectCard], summary="Project exploration cards")
def projects(request: Request) -> list[ProjectCard]:
    container = get_container(request)
    career: CareerService = container.career_service
    return [ProjectCard(**card) for card in career.get_projects()]


@api_router.get("/config/status", response_model=ConfigStatus, summary="Non-secret config status")
def config_status(settings: Settings = Depends(get_settings_dep)) -> ConfigStatus:
    """Runtime configuration snapshot. Secrets are never included (booleans only)."""
    return ConfigStatus(
        version=__version__,
        app_env=settings.app_env,
        log_level=settings.log_level,
        api_prefix=settings.api_prefix,
        qdrant_url=settings.qdrant_url,
        qdrant_collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model,
        reranker_model=settings.reranker_model,
        reranker_enabled=settings.enable_reranker,
        llm_provider=settings.llm_provider,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_api_key_configured=bool(settings.llm_api_key),
        llm_temperature=settings.llm_temperature,
        llm_max_tokens=settings.llm_max_tokens,
        top_k_retrieval=settings.top_k_retrieval,
        top_n_reranked=settings.top_n_reranked,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        min_chunk_length=settings.min_chunk_length,
        max_query_length=settings.max_query_length,
        max_job_description_length=settings.max_job_description_length,
        max_document_length=settings.max_document_length,
        api_key_enabled=settings.api_key_enabled,
        debug_endpoints_enabled=settings.enable_debug_endpoints,
        public_profile_mode=settings.public_profile_mode,
        show_contact_information=settings.show_contact_information,
        allowed_origins=settings.origins_list,
        links={
            "github": settings.github_url,
            "linkedin": settings.linkedin_url,
            "portfolio": settings.portfolio_url,
        },
    )
