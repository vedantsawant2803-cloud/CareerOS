"""API tests: request validation, mode rules, and safe error responses."""

from __future__ import annotations

import pytest


def _post(client, payload: dict):
    base = {
        "query": "What is DevLens?",
        "mode": "qa",
        "job_description": None,
        "filters": {"project": None, "document_type": None, "technology": None, "year": None},
        "include_debug": False,
    }
    base.update(payload)
    return client.post("/api/v1/query", json=base)


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------
def test_empty_query_rejected(client):
    response = _post(client, {"query": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "validation_error"
    assert "query" in body["detail"].lower()


def test_whitespace_only_query_rejected(client):
    response = _post(client, {"query": "    \n  "})
    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_missing_query_field_rejected(client):
    response = client.post("/api/v1/query", json={"mode": "qa"})
    assert response.status_code == 422
    assert response.json()["type"] == "validation_error"


def test_query_length_limit_enforced(client, settings):
    long_query = "a" * (settings.max_query_length + 1)
    response = _post(client, {"query": long_query})
    assert response.status_code == 422
    assert "MAX_QUERY_LENGTH" in response.json()["detail"]


def test_job_description_length_limit_enforced(client, settings):
    long_jd = "b" * (settings.max_job_description_length + 1)
    response = _post(
        client,
        {"query": "Tailor this", "mode": "tailor_resume", "job_description": long_jd},
    )
    assert response.status_code == 422
    assert "MAX_JOB_DESCRIPTION_LENGTH" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------
def test_unknown_mode_rejected(client):
    response = _post(client, {"mode": "summarize_everything"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Unsupported mode" in detail
    # The error lists the supported modes for discoverability.
    assert "resume_bullets" in detail


@pytest.mark.parametrize("mode", ["qa", "project_summary", "interview_prep", "resume_bullets"])
def test_supported_modes_accepted_without_job_description(
    client, mode, sample_corpus, test_container
):
    test_container.pipeline.run(data_dir=sample_corpus)
    response = _post(client, {"query": "Tell me about the project", "mode": mode})
    assert response.status_code == 200
    assert response.json()["mode"] == mode


# ---------------------------------------------------------------------------
# Job description requirements
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["tailor_resume", "skill_gap"])
def test_job_description_required(client, mode):
    response = _post(client, {"mode": mode, "job_description": None})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "job_description" in detail
    assert mode in detail


def test_blank_job_description_rejected_for_tailor_resume(client):
    response = _post(
        client,
        {"mode": "tailor_resume", "job_description": "   \n "},
    )
    assert response.status_code == 422
    assert "job_description" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Filter validation
# ---------------------------------------------------------------------------
def test_out_of_range_year_rejected(client):
    response = _post(
        client,
        {"filters": {"project": None, "document_type": None, "technology": None, "year": 1200}},
    )
    assert response.status_code == 422


def test_blank_filter_values_normalised_to_null(client, sample_corpus, test_container):
    test_container.pipeline.run(data_dir=sample_corpus)
    response = _post(
        client,
        {"filters": {"project": "  ", "document_type": "", "technology": None, "year": None}},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Ingest validation
# ---------------------------------------------------------------------------
def test_ingest_rejects_absolute_path(client):
    response = client.post("/api/v1/ingest", json={"data_dir": "/etc/passwd"})
    assert response.status_code == 422
    assert "relative" in response.json()["detail"]


def test_ingest_rejects_parent_directory_traversal(client):
    response = client.post("/api/v1/ingest", json={"data_dir": "../../secrets"})
    assert response.status_code == 422


def test_ingest_missing_directory_returns_400_not_stack_trace(client):
    response = client.post("/api/v1/ingest", json={"data_dir": "data/does_not_exist"})
    assert response.status_code == 400
    body = response.json()
    assert body["type"] == "bad_request"
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# Error response safety
# ---------------------------------------------------------------------------
def test_unhandled_errors_do_not_leak_stack_traces_in_production(settings, test_container):
    from app.main import create_app
    from fastapi.testclient import TestClient

    production_settings = settings.model_copy(
        update={
            "app_env": "production",
            "allowed_origins": "https://example.com",
            "api_key_enabled": False,
            "enable_debug_endpoints": False,
            "show_contact_information": False,
            "qdrant_url": "http://qdrant:6333",
            "llm_base_url": "https://llm.internal.example.com/v1",
        }
    )
    app = create_app(settings=production_settings, container=test_container)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("internal secret value: hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail == "An unexpected error occurred."
        assert "hunter2" not in response.text
        assert "Traceback" not in response.text
        assert "RuntimeError" not in response.text


def test_error_envelope_shape_for_validation(client):
    response = _post(client, {"query": ""})
    body = response.json()
    assert set(body.keys()) == {"detail", "type"}
    assert isinstance(body["detail"], str)
    assert body["type"] == "validation_error"
