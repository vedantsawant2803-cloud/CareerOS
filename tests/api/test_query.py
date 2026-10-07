"""API tests: the /api/v1/query endpoint with mocked retrieval and LLM."""

from __future__ import annotations

import pytest

REQUIRED_METADATA_KEYS = {"retrieval_count", "latency_ms", "llm_model", "confidence"}


@pytest.fixture
def seeded_client(client, test_container, sample_corpus):
    """Client with the fake vector store populated from the sample corpus."""
    test_container.pipeline.run(data_dir=sample_corpus)
    return client


def _query(client, **overrides):
    payload = {
        "query": "Which projects demonstrate backend engineering?",
        "mode": "qa",
        "job_description": None,
        "filters": {"project": None, "document_type": None, "technology": None, "year": None},
        "include_debug": False,
    }
    payload.update(overrides)
    return client.post("/api/v1/query", json=payload)


def test_successful_query_response_shape(seeded_client):
    response = _query(seeded_client)
    assert response.status_code == 200
    body = response.json()

    assert body["answer"]
    assert body["mode"] == "qa"
    assert isinstance(body["citations"], list)
    assert len(body["citations"]) >= 1
    assert REQUIRED_METADATA_KEYS.issubset(body["metadata"].keys())

    citation = body["citations"][0]
    for key in ("source_file", "document_type", "title", "section", "chunk_id", "quote"):
        assert key in citation
    assert citation["source_file"].endswith(".md")
    assert citation["quote"]


def test_retrieved_chunks_hidden_by_default_but_available_with_debug(seeded_client):
    hidden = _query(seeded_client, include_debug=False).json()
    assert hidden["retrieved_chunks"] == []

    debug = _query(seeded_client, include_debug=True).json()
    assert len(debug["retrieved_chunks"]) >= 1
    chunk = debug["retrieved_chunks"][0]
    for key in (
        "rank",
        "chunk_id",
        "text",
        "source_file",
        "title",
        "section",
        "document_type",
        "technologies",
        "vector_score",
        "rerank_score",
    ):
        assert key in chunk
    assert isinstance(chunk["vector_score"], float)
    # Reranking disabled in tests → rerank_score is null, never a crash.
    assert chunk["rerank_score"] is None


def test_metadata_contains_reranker_fallback_warning(seeded_client):
    body = _query(seeded_client, include_debug=True).json()
    warnings = body["metadata"]["warnings"]
    assert any("rerank" in warning.lower() for warning in warnings)
    assert body["metadata"]["confidence"] in {"high", "medium", "low", "none"}
    assert body["metadata"]["retrieval_count"] == len(body["retrieved_chunks"])


def test_technology_filter_restricts_citations(seeded_client):
    body = _query(
        seeded_client,
        query="Tell me about the database usage",
        filters={
            "project": None,
            "document_type": None,
            "technology": "MySQL",
            "year": None,
        },
        include_debug=True,
    ).json()
    assert body["metadata"]["retrieval_count"] >= 1
    for chunk in body["retrieved_chunks"]:
        assert "MySQL" in chunk["technologies"]


def test_project_filter_restricts_sources(seeded_client):
    body = _query(
        seeded_client,
        query="What does this project do?",
        filters={
            "project": "sample_project",
            "document_type": None,
            "technology": None,
            "year": None,
        },
        include_debug=True,
    ).json()
    assert body["metadata"]["retrieval_count"] >= 1
    for chunk in body["retrieved_chunks"]:
        assert chunk["source_file"] == "sample_project.md"


def test_empty_index_returns_cautious_answer(settings, test_container, client):
    """No chunks indexed → explicit insufficient-information answer, no fabrication."""
    body = _query(client, query="What is DevLens?").json()
    assert "does not contain enough information" in body["answer"]
    assert body["citations"] == []
    assert body["metadata"]["retrieval_count"] == 0
    assert body["metadata"]["confidence"] == "none"


def test_resume_bullets_mode(seeded_client):
    body = _query(
        seeded_client,
        query="Generate resume bullets about backend work",
        mode="resume_bullets",
    ).json()
    assert body["mode"] == "resume_bullets"
    assert body["answer"]
    assert body["citations"]


def test_interview_prep_mode(seeded_client):
    body = _query(
        seeded_client,
        query="Generate interview questions about this project",
        mode="interview_prep",
    ).json()
    assert body["mode"] == "interview_prep"
    assert body["answer"]


def test_project_summary_mode(seeded_client):
    body = _query(
        seeded_client,
        query="Summarize the sample project",
        mode="project_summary",
    ).json()
    assert body["mode"] == "project_summary"
    assert body["citations"]


def test_tailor_resume_mode_with_job_description(seeded_client):
    body = _query(
        seeded_client,
        query="Tailor the profile for a backend role",
        mode="tailor_resume",
        job_description="Backend intern using Node.js, Express, and MySQL.",
    ).json()
    assert body["mode"] == "tailor_resume"
    assert body["answer"]


def test_skill_gap_mode_with_job_description(seeded_client):
    body = _query(
        seeded_client,
        query="Compare against this job",
        mode="skill_gap",
        job_description="Requirements: Node.js, REST APIs, MySQL, testing.",
    ).json()
    assert body["mode"] == "skill_gap"
    assert body["answer"]


def test_api_key_required_when_enabled(settings, test_container, seeded_client):
    from app.main import create_app
    from fastapi.testclient import TestClient

    secured = settings.model_copy(
        update={"api_key_enabled": True, "api_key": "unit-test-key-1234567890"}
    )
    app = create_app(settings=secured, container=test_container)
    with TestClient(app) as client:
        denied = client.post("/api/v1/query", json={"query": "What is DevLens?"})
        assert denied.status_code == 401
        assert denied.json()["type"] == "http_error"

        allowed = client.post(
            "/api/v1/query",
            json={"query": "What is DevLens?"},
            headers={"X-API-Key": "unit-test-key-1234567890"},
        )
        assert allowed.status_code == 200


def test_ingest_endpoint_indexes_documents(seeded_client):
    import os
    from pathlib import Path

    # The API only accepts relative paths inside the workspace.
    data_dir = os.environ.get("DATA_DIR", "data/sample_docs")
    try:
        relative = os.path.relpath(data_dir, Path.cwd())
    except ValueError:  # different drive on Windows
        relative = "data/sample_docs"
    if relative.startswith(".."):
        relative = "data/sample_docs"

    response = seeded_client.post(
        "/api/v1/ingest",
        json={"data_dir": relative, "reset": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] >= 5
    assert body["chunks"] > 0
    assert body["indexed"] == body["chunks"]
    assert body["collection"]
    assert body["embedding_model"]
    assert body["reranker_model"]


def test_profile_endpoint_hides_contact_by_default(seeded_client):
    body = seeded_client.get("/api/v1/profile").json()
    assert body["name"] == "Vedant Sawant"
    assert body["contact"] is None
    assert body["skills"]
    assert "9321805753" not in seeded_client.get("/api/v1/profile").text
    assert "vedantsawant2803@gmail.com" not in seeded_client.get("/api/v1/profile").text
    assert body["current_learning"]


def test_profile_endpoint_exposes_contact_only_when_enabled(settings, test_container):
    from app.main import create_app
    from fastapi.testclient import TestClient

    enabled = settings.model_copy(
        update={"show_contact_information": True, "app_env": "development"}
    )
    # The career service reads privacy flags from the settings it was built with.
    test_container.career_service.settings = enabled
    app = create_app(settings=enabled, container=test_container)
    with TestClient(app) as client:
        body = client.get("/api/v1/profile").json()
        assert body["contact"]["email"] == "vedantsawant2803@gmail.com"


def test_projects_endpoint_returns_cards(seeded_client):
    response = seeded_client.get("/api/v1/projects")
    assert response.status_code == 200
    cards = response.json()
    names = [card["name"] for card in cards]
    assert len(cards) >= 5
    assert any("DevLens" in name for name in names)
    assert any("EnviroMonitor" in name for name in names)
    assert any("Apartment Visitor Security System" in name for name in names)
    assert any("Google Developer Group" in name for name in names)
    assert any("SIES" in name for name in names)

    for card in cards:
        assert card["subtitle"]
        assert card["technologies"]
        assert card["description"]
        assert card["citation"]["source_file"].endswith(".md")
        assert card["citation"]["quote"]
