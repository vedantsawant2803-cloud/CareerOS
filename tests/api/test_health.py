"""API tests: health and meta endpoints."""

from __future__ import annotations


def test_health_returns_status_document(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded", "unavailable"}
    assert body["environment"] == "test"
    assert isinstance(body["ready"], bool)
    assert "qdrant" in body["checks"]
    assert "embeddings" in body["checks"]
    assert "reranker" in body["checks"]
    assert "llm" in body["checks"]


def test_health_does_not_leak_secrets(client):
    response = client.get("/health")
    assert response.status_code == 200
    text = response.text.lower()
    assert "api_key" not in text
    assert "x-api-key" not in text


def test_health_reports_llm_configuration_without_key(client):
    body = client.get("/health").json()
    llm = body["checks"]["llm"]
    assert "model" in llm
    assert "base_url" in llm
    assert "api_key" not in llm


def test_root_service_metadata(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "CareerOS"
    assert body["api_prefix"] == "/api/v1"
    assert body["docs"] == "/docs"


def test_config_status_shape_and_safety(client):
    response = client.get("/api/v1/config/status")
    assert response.status_code == 200
    body = response.json()

    expected_keys = {
        "version",
        "app_env",
        "log_level",
        "api_prefix",
        "qdrant_url",
        "qdrant_collection",
        "embedding_model",
        "reranker_model",
        "reranker_enabled",
        "llm_provider",
        "llm_base_url",
        "llm_model",
        "llm_api_key_configured",
        "top_k_retrieval",
        "top_n_reranked",
        "chunk_size",
        "max_query_length",
        "api_key_enabled",
        "debug_endpoints_enabled",
        "public_profile_mode",
        "show_contact_information",
        "links",
    }
    assert expected_keys.issubset(set(body.keys()))

    # Booleans only — never secret values.
    assert isinstance(body["llm_api_key_configured"], bool)
    assert isinstance(body["api_key_enabled"], bool)
    assert "llm_api_key" not in body
    assert "api_key" not in body


def test_config_status_never_contains_secret_values(settings, test_container):
    """Even when secrets are configured, only booleans are exposed."""
    from app.main import create_app
    from fastapi.testclient import TestClient

    secret_settings = settings.model_copy(
        update={
            "api_key": "super-secret-api-key-1234567890",
            "api_key_enabled": True,
            "llm_api_key": "super-secret-llm-key-1234567890",
        }
    )
    app = create_app(settings=secret_settings, container=test_container)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/config/status",
            headers={"X-API-Key": "super-secret-api-key-1234567890"},
        )
        assert response.status_code == 200
        assert "super-secret" not in response.text
        body = response.json()
        assert body["llm_api_key_configured"] is True
        assert body["api_key_enabled"] is True
