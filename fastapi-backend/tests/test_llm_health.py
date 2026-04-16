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
    probe_completion,
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


@respx.mock
async def test_probe_litellm_proxy_with_base_url_ok():
    """When LLM_BASE_URL + key are set, validate against the proxy, not Anthropic."""
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-litellm-key-1234567890"
        mock_settings.LLM_BASE_URL = "https://litellm.example.com"
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        respx.get("https://litellm.example.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = await probe_provider()
        assert result.status == "ok"
        assert result.message == "API key is valid"


@respx.mock
async def test_probe_litellm_proxy_auth_error():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-bad-key"
        mock_settings.LLM_BASE_URL = "https://litellm.example.com"
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        respx.get("https://litellm.example.com/v1/models").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )

        result = await probe_provider()
        assert result.status == "auth_error"


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


# ── probe_completion ─────────────────────────────────────────────────────────


async def test_probe_completion_not_configured():
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "bedrock/anthropic.claude-3-sonnet"

        result = await probe_completion()
        assert result.status == "not_configured"


async def test_probe_completion_ok():
    """A clean litellm.acompletion call surfaces as ok."""
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-ant-test1234abcdef"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        async def _fake_acompletion(**kwargs):
            return {"choices": [{"message": {"content": "p"}}]}

        with patch("litellm.acompletion", side_effect=_fake_acompletion):
            result = await probe_completion()

        assert result.status == "ok"
        assert "succeeded" in result.message.lower()


async def test_probe_completion_missing_provider_sdk():
    """A ModuleNotFoundError raised by litellm becomes `missing_extras` with a hint."""
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = ""
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "bedrock/anthropic.claude-3-sonnet"

        async def _raise(**kwargs):
            raise ModuleNotFoundError("No module named 'boto3'")

        with patch("litellm.acompletion", side_effect=_raise):
            # Override config not_configured by pretending a key is set.
            mock_settings.LLM_API_KEY = "aws-access-key-id"
            result = await probe_completion()

        assert result.status == "missing_extras"
        assert "bedrock" in result.message.lower() or "boto3" in result.message.lower()
        assert result.remediation is not None
        assert "boto3" in result.remediation


async def test_probe_completion_wrapped_import_error_in_message():
    """litellm sometimes wraps missing-SDK errors in a generic Exception whose
    message embeds 'No module named X' — we should still classify as
    missing_extras."""
    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "aws-key"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "bedrock/anthropic.claude-3-sonnet"

        async def _raise(**kwargs):
            raise Exception("No module named 'boto3' — pip install boto3")

        with patch("litellm.acompletion", side_effect=_raise):
            result = await probe_completion()

        assert result.status == "missing_extras"
        assert result.remediation is not None


async def test_probe_completion_auth_error():
    """litellm.AuthenticationError maps to auth_error with a remediation."""
    import litellm

    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-ant-bad"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"

        async def _raise(**kwargs):
            raise litellm.AuthenticationError(
                message="invalid key", llm_provider="anthropic", model="claude-sonnet-4-6"
            )

        with patch("litellm.acompletion", side_effect=_raise):
            result = await probe_completion()

        assert result.status == "auth_error"
        assert result.remediation is not None
        assert "LLM_API_KEY" in result.remediation


async def test_probe_completion_bad_model():
    """litellm.BadRequestError on an unknown model surfaces as bad_model."""
    import litellm

    with patch("app.services.llm_health.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-test"
        mock_settings.LLM_BASE_URL = None
        mock_settings.LLM_MODEL = "anthropic/claude-imaginary-model"

        async def _raise(**kwargs):
            raise litellm.BadRequestError(
                message="unknown model", llm_provider="anthropic", model="claude-imaginary"
            )

        with patch("litellm.acompletion", side_effect=_raise):
            result = await probe_completion()

        assert result.status == "bad_model"


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


async def test_health_check_llm_completion_probe(client: AsyncClient):
    """/health?check_llm=true&llm_probe=completion triggers the completion probe."""
    resp = await client.get(
        "/health",
        params={"check_llm": "true", "llm_probe": "completion"},
    )
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
        "missing_extras",
        "bad_model",
        "error",
    )
    # remediation is part of the new schema
    assert "remediation" in llm


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
