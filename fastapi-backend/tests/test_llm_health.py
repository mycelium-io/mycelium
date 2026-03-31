"""
Tests for health checking: LLM key validation, database connectivity,
embedding model status, version info, and the /health endpoint.
"""

from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.services.llm_health import (
    get_config_status,
    invalidate_cache,
    mask_key,
    probe_provider,
    validate_key_format,
)

pytestmark = pytest.mark.asyncio

# ── mask_key ──────────────────────────────────────────────────────────────────


def test_mask_key_normal():
    assert mask_key("sk-ant-abc123xyz456") == "sk-...z456"


def test_mask_key_short():
    assert mask_key("short") == "***"


def test_mask_key_exact_boundary():
    assert mask_key("12345678") == "***"
    assert mask_key("123456789") == "123...6789"


# ── validate_key_format ──────────────────────────────────────────────────────


def test_format_valid_openai():
    assert validate_key_format("sk-proj-abc123", "openai") is None
    assert validate_key_format("sk-abc123xyz", "openai") is None


def test_format_valid_anthropic():
    assert validate_key_format("sk-ant-abc123", "anthropic") is None


def test_format_invalid_openai():
    err = validate_key_format("wrong-key-here", "openai")
    assert err is not None
    assert "openai" in err


def test_format_invalid_anthropic():
    err = validate_key_format("sk-openai-key", "anthropic")
    assert err is not None
    assert "anthropic" in err


def test_format_unknown_provider():
    assert validate_key_format("any-key", "some_other_provider") is None


# ── get_config_status ────────────────────────────────────────────────────────


def test_config_not_configured():
    with (
        patch("app.services.llm_health.settings") as mock_settings,
    ):
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        result = get_config_status()
        assert result.status == "not_configured"
        assert result.configured is False
        assert result.key_hint is None


def test_config_valid_key():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-ant-test1234abcdef"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        result = get_config_status()
        assert result.status == "ok"
        assert result.configured is True
        assert result.key_hint == "sk-...cdef"
        assert result.key_required is True


def test_config_unrecognized_format_still_ok():
    """A key with an unrecognized prefix is a warning, not a rejection."""
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "wrong-format-key"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        result = get_config_status()
        assert result.status == "ok"
        assert result.configured is True
        assert "warning" in result.message.lower()


def test_config_ollama_no_key():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = "http://localhost:11434"
        mock_settings.LLM_MODEL = "ollama/llama3"

        result = get_config_status()
        assert result.status == "ok"
        assert result.key_required is False
        assert result.key_hint is None


# ── probe_provider ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure probe cache is clean for each test."""
    invalidate_cache()
    yield
    invalidate_cache()


@respx.mock
async def test_probe_anthropic_ok():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-ant-test1234abcdef"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        respx.get("https://api.anthropic.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = await probe_provider()
        assert result.status == "ok"
        assert result.message == "API key is valid"


@respx.mock
async def test_probe_anthropic_auth_error():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-ant-expired1234abc"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        respx.get("https://api.anthropic.com/v1/models").mock(
            return_value=httpx.Response(401, json={"error": "invalid_api_key"})
        )

        result = await probe_provider()
        assert result.status == "auth_error"
        assert "invalid or expired" in result.message


@respx.mock
async def test_probe_openai_ok():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-test1234abcdef9876"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "openai/gpt-4o"

        respx.get("https://api.openai.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = await probe_provider()
        assert result.status == "ok"


@respx.mock
async def test_probe_openai_unreachable():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-test1234abcdef9876"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "openai/gpt-4o"

        respx.get("https://api.openai.com/v1/models").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        result = await probe_provider()
        assert result.status == "unreachable"


async def test_probe_unknown_provider():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "some-key-1234567890"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "mistral/mistral-large"

        result = await probe_provider()
        assert result.status == "unchecked"
        assert "not supported" in result.message


@respx.mock
async def test_probe_ollama_connectivity():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = "http://localhost:11434"
        mock_settings.LLM_MODEL = "ollama/llama3"

        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )

        result = await probe_provider()
        assert result.status == "ok"
        assert result.key_required is False


@respx.mock
async def test_probe_ollama_unreachable():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = "http://localhost:11434"
        mock_settings.LLM_MODEL = "ollama/llama3"

        respx.get("http://localhost:11434/api/tags").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        result = await probe_provider()
        assert result.status == "unreachable"
        assert "Ollama" in result.message


# ── /health endpoint ─────────────────────────────────────────────────────────


async def test_health_includes_llm_config(client: AsyncClient):
    """Basic /health returns llm config status (no probe)."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm" in data
    assert "status" in data["llm"]
    assert "model" in data["llm"]


async def test_health_check_llm_probe(client: AsyncClient):
    """/health?check_llm=true triggers the provider probe."""
    resp = await client.get("/health", params={"check_llm": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert "llm" in data
    llm = data["llm"]
    assert llm["status"] in (
        "ok",
        "not_configured",
        "auth_error",
        "unreachable",
        "unchecked",
    )


# ── /health: database ────────────────────────────────────────────────────────


async def test_health_includes_database(client: AsyncClient):
    """/health includes database connectivity status."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "database" in data
    db = data["database"]
    assert db["status"] in ("ok", "unreachable")
    assert "message" in db


async def test_health_database_connected(client: AsyncClient):
    """With the test DB session injected via DI, database should be reachable."""
    resp = await client.get("/health")
    data = resp.json()
    assert data["database"]["status"] == "ok"


# ── /health: embedding ───────────────────────────────────────────────────────


async def test_health_includes_embedding(client: AsyncClient):
    """/health includes embedding model status."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "embedding" in data
    embed = data["embedding"]
    assert embed["status"] in ("ok", "not_cached", "stub")
    assert "model" in embed
    assert "message" in embed


# ── /health: version ─────────────────────────────────────────────────────────


async def test_health_includes_version(client: AsyncClient):
    """/health returns the backend version string."""
    resp = await client.get("/health")
    data = resp.json()
    assert "version" in data
    assert isinstance(data["version"], str)
    assert len(data["version"]) > 0


# ── /health: overall status ──────────────────────────────────────────────────


async def test_health_overall_status_ok_or_degraded(client: AsyncClient):
    """Overall status should be 'ok' or 'degraded', never missing."""
    resp = await client.get("/health")
    data = resp.json()
    assert data["status"] in ("ok", "degraded")


async def test_health_response_structure(client: AsyncClient):
    """Verify the complete /health response structure."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    expected_keys = {"status", "service", "version", "database", "embedding", "llm"}
    assert expected_keys.issubset(data.keys())
