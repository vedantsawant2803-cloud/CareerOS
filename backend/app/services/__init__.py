"""Service layer: orchestration between API, retrieval, and generation."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for user-safe service failures."""

    status_code: int = 500
    error_type: str = "service_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequestError(ServiceError):
    """Invalid input for the requested operation."""

    status_code = 400
    error_type = "bad_request"


class ServiceUnavailableError(ServiceError):
    """A dependency (Qdrant, embeddings, index) is not available."""

    status_code = 503
    error_type = "service_unavailable"
