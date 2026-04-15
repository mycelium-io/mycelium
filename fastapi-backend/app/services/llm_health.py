"""
LLM health checking: key format validation, masked key hints, and
zero-cost provider probes using read-only model-list endpoints.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Known key-prefix patterns (provider → expected prefixes)
_KEY_FORMATS: dict[str, list[str]] = {
    "openai": ["sk-"],
    "anthropic": ["sk-ant-"],
}

# Provider model-list endpoints for zero-cost key validation
_MODEL_LIST_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}

_PROBE_TIMEOUT = 10
_CACHE_TTL_SECONDS = 60


@dataclass
class LLMHealthResult:
    # ok | auth_error | unreachable | not_configured | unchecked
    # | missing_extras | bad_model | error
    status: str
    model: str
    configured: bool
    key_hint: str | None
    key_required: bool
    message: str
    remediation: str | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "model": self.model,
            "configured": self.configured,
            "key_hint": self.key_hint,
            "key_required": self.key_required,
            "message": self.message,
            "remediation": self.remediation,
            "checked_at": self.checked_at,
        }


# Simple in-memory cache for probe results
_cached_result: LLMHealthResult | None = None
_cached_at: float = 0.0


def _detect_provider() -> str:
    """Infer the LLM provider from LLM_MODEL (e.g. 'anthropic/claude-...' -> 'anthropic')."""
    model = settings.LLM_MODEL
    if "/" in model:
        return model.split("/", 1)[0].lower()
    return "unknown"


def mask_key(key: str) -> str:
    """Return a masked hint showing only the first 3 and last 4 characters."""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}...{key[-4:]}"


def validate_key_format(key: str, provider: str) -> str | None:
    """Check key format against known provider patterns.

    Returns an error message if the format is wrong, or None if it looks valid
    (or the provider has no known format).
    """
    prefixes = _KEY_FORMATS.get(provider)
    if not prefixes:
        return None
    if any(key.startswith(p) for p in prefixes):
        return None
    expected = " or ".join(f"'{p}...'" for p in prefixes)
    return f"Key does not match expected {provider} format ({expected})"


def get_config_status() -> LLMHealthResult:
    """Level A: config and format check only (no network)."""
    model = settings.LLM_MODEL
    provider = _detect_provider()
    has_key = bool(settings.LLM_API_KEY)
    has_base_url = bool(settings.LLM_BASE_URL)
    key_hint = mask_key(settings.LLM_API_KEY) if has_key else None

    is_local = provider == "ollama" or (has_base_url and not has_key)
    key_required = not is_local

    if not has_key and not has_base_url:
        return LLMHealthResult(
            status="not_configured",
            model=model,
            configured=False,
            key_hint=None,
            key_required=True,
            message="No LLM_API_KEY or LLM_BASE_URL set. LLM features are disabled.",
        )

    fmt_warning: str | None = None
    if has_key:
        fmt_warning = validate_key_format(settings.LLM_API_KEY, provider)
        if fmt_warning:
            logger.warning("LLM key format warning: %s", fmt_warning)

    if fmt_warning:
        msg = f"LLM configured (warning: {fmt_warning})"
    elif has_key:
        msg = "LLM configured (key format valid)"
    else:
        msg = "LLM configured (local endpoint)"

    return LLMHealthResult(
        status="ok",
        model=model,
        configured=True,
        key_hint=key_hint,
        key_required=key_required,
        message=msg,
    )


async def probe_provider() -> LLMHealthResult:
    """Level B: zero-cost provider probe via model-list endpoints.

    Uses free read-only endpoints for OpenAI/Anthropic, connectivity check
    for Ollama, and reports 'unchecked' for unknown providers.
    Results are cached for 60 seconds.
    """
    global _cached_result, _cached_at

    now = time.monotonic()
    if _cached_result is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_result

    config_result = get_config_status()
    if config_result.status == "not_configured":
        _cached_result = config_result
        _cached_at = now
        return config_result

    provider = _detect_provider()
    model = settings.LLM_MODEL

    try:
        result = await _probe_by_provider(provider, model, config_result)
    except Exception:
        logger.exception("LLM health probe failed unexpectedly")
        result = LLMHealthResult(
            status="unreachable",
            model=model,
            configured=True,
            key_hint=config_result.key_hint,
            key_required=config_result.key_required,
            message="Health probe failed unexpectedly",
        )

    _cached_result = result
    _cached_at = now
    return result


async def _probe_by_provider(provider: str, model: str, config: LLMHealthResult) -> LLMHealthResult:
    """Dispatch to the appropriate provider-specific probe."""
    base = {
        "model": model,
        "configured": True,
        "key_hint": config.key_hint,
        "key_required": config.key_required,
    }

    if provider == "ollama" or (settings.LLM_BASE_URL and not settings.LLM_API_KEY):
        return await _probe_ollama(**base)

    # LiteLLM and other OpenAI-compatible proxies: key is valid only at the proxy,
    # not at api.anthropic.com — probe the custom base URL.
    if settings.LLM_BASE_URL and settings.LLM_API_KEY:
        return await _probe_openai_compatible_proxy(**base)

    endpoint = _MODEL_LIST_ENDPOINTS.get(provider)
    if endpoint:
        return await _probe_api_key(endpoint, provider, **base)

    return LLMHealthResult(
        status="unchecked",
        message="Key validation not supported for this provider. Key is configured but could not be verified.",
        **base,
    )


async def _probe_openai_compatible_proxy(**base) -> LLMHealthResult:
    """Probe LLM_BASE_URL using OpenAI-compatible GET /v1/models (LiteLLM, etc.)."""
    raw_base = settings.LLM_BASE_URL or ""
    base_url = raw_base.rstrip("/")
    models_url = f"{base_url}/v1/models"
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(models_url, headers=headers)
        except httpx.ConnectError:
            return LLMHealthResult(
                status="unreachable",
                message=f"Cannot connect to LLM proxy at {base_url}",
                **base,
            )
        except httpx.TimeoutException:
            return LLMHealthResult(
                status="unreachable",
                message=f"Timeout connecting to LLM proxy at {base_url}",
                **base,
            )

        if resp.status_code == 200:
            return LLMHealthResult(status="ok", message="API key is valid", **base)
        if resp.status_code in (401, 403):
            return LLMHealthResult(
                status="auth_error",
                message="API key is invalid or expired",
                **base,
            )
        return LLMHealthResult(
            status="unreachable",
            message=f"LLM proxy returned unexpected status {resp.status_code}",
            **base,
        )


async def _probe_api_key(endpoint: str, provider: str, **base) -> LLMHealthResult:
    """Probe OpenAI or Anthropic via their free model-list endpoint."""
    headers: dict[str, str] = {}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    elif provider == "anthropic":
        headers["x-api-key"] = settings.LLM_API_KEY
        headers["anthropic-version"] = "2023-06-01"

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(endpoint, headers=headers)
        except httpx.ConnectError:
            return LLMHealthResult(
                status="unreachable",
                message=f"Cannot connect to {provider} API",
                **base,
            )
        except httpx.TimeoutException:
            return LLMHealthResult(
                status="unreachable",
                message=f"Timeout connecting to {provider} API",
                **base,
            )

    if resp.status_code == 200:
        return LLMHealthResult(status="ok", message="API key is valid", **base)
    if resp.status_code in (401, 403):
        return LLMHealthResult(
            status="auth_error",
            message="API key is invalid or expired",
            **base,
        )
    return LLMHealthResult(
        status="unreachable",
        message=f"{provider} API returned unexpected status {resp.status_code}",
        **base,
    )


async def _probe_ollama(**base) -> LLMHealthResult:
    """Connectivity check for Ollama (no key required)."""
    base_url = (settings.LLM_BASE_URL or "http://localhost:11434").rstrip("/")
    tags_url = f"{base_url}/api/tags"

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(tags_url)
        except httpx.ConnectError:
            return LLMHealthResult(
                status="unreachable",
                message=f"Cannot connect to Ollama at {base_url}",
                **base,
            )
        except httpx.TimeoutException:
            return LLMHealthResult(
                status="unreachable",
                message=f"Timeout connecting to Ollama at {base_url}",
                **base,
            )

    if resp.status_code == 200:
        return LLMHealthResult(status="ok", message="Ollama is reachable", **base)
    return LLMHealthResult(
        status="unreachable",
        message=f"Ollama returned unexpected status {resp.status_code}",
        **base,
    )


def invalidate_cache() -> None:
    """Clear the probe cache (useful after config changes)."""
    global _cached_result, _cached_at, _cached_completion, _cached_completion_at
    _cached_result = None
    _cached_at = 0.0
    _cached_completion = None
    _cached_completion_at = 0.0


# ── Completion probe ─────────────────────────────────────────────────────────
#
# probe_provider() uses provider-specific model-list endpoints (free, zero-token)
# but only knows about openai/anthropic/ollama/openai-compatible proxies. It
# reports "unchecked" for everything else — which means a user with a broken
# Bedrock or Vertex config sees a green tick until their first real inference.
#
# probe_completion() actually calls litellm.acompletion(max_tokens=1) so it
# exercises the real code path and surfaces problems that only show up on the
# first inference: missing provider SDKs (boto3 for Bedrock, google-cloud-aiplatform
# for Vertex, etc.), bad model strings, and auth errors at the true endpoint.


# Map the provider prefix used in litellm model strings to the package the user
# needs to install.  Used only for remediation hints when we detect a missing SDK.
_PROVIDER_EXTRAS: dict[str, str] = {
    "bedrock": "boto3",
    "sagemaker": "boto3",
    "vertex_ai": "google-cloud-aiplatform",
    "vertex": "google-cloud-aiplatform",
    "gemini": "google-generativeai",
    "azure": "openai",
    "cohere": "cohere",
    "watsonx": "ibm-watsonx-ai",
}


_cached_completion: LLMHealthResult | None = None
_cached_completion_at: float = 0.0


def _missing_sdk_remediation(provider: str, raw_message: str) -> str:
    """Build an actionable install hint for a missing provider SDK."""
    pkg = _PROVIDER_EXTRAS.get(provider)
    if pkg:
        return f"Install the provider SDK in the backend container: pip install {pkg}"
    # Fall back to surfacing the underlying import error — litellm often embeds
    # the correct pip command in its own message.
    return f"Install the provider SDK: {raw_message}"


async def probe_completion() -> LLMHealthResult:
    """Level C: real completion probe via ``litellm.acompletion(max_tokens=1)``.

    Surfaces three failure modes that ``probe_provider()`` cannot:

    1. Missing provider SDK extras (e.g. boto3 for Bedrock) — reported as
       ``missing_extras`` with an actionable ``pip install`` hint.
    2. Bad model strings — reported as ``bad_model``.
    3. Auth failures at the actual inference endpoint (not just the model-list
       endpoint) — reported as ``auth_error``.

    Cached for 60s to avoid hammering the provider on repeated doctor runs.
    """
    global _cached_completion, _cached_completion_at

    now = time.monotonic()
    if _cached_completion is not None and (now - _cached_completion_at) < _CACHE_TTL_SECONDS:
        return _cached_completion

    config_result = get_config_status()
    if config_result.status == "not_configured":
        _cached_completion = config_result
        _cached_completion_at = now
        return config_result

    provider = _detect_provider()
    model = settings.LLM_MODEL

    base = {
        "model": model,
        "configured": True,
        "key_hint": config_result.key_hint,
        "key_required": config_result.key_required,
    }

    # Lazy import: litellm is a heavy dep, only pull it in when we actually probe.
    try:
        import litellm
    except ImportError as exc:
        result = LLMHealthResult(
            status="error",
            message=f"litellm not available in backend: {exc}",
            remediation="Reinstall backend dependencies: uv sync",
            **base,
        )
        _cached_completion = result
        _cached_completion_at = now
        return result

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "timeout": _PROBE_TIMEOUT,
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    try:
        await litellm.acompletion(**kwargs)
        result = LLMHealthResult(
            status="ok",
            message="Completion probe succeeded",
            **base,
        )
    except ModuleNotFoundError as exc:
        # Missing provider SDK extras (boto3, google-cloud-aiplatform, ...).
        result = LLMHealthResult(
            status="missing_extras",
            message=f"Missing provider SDK for {provider}: {exc}",
            remediation=_missing_sdk_remediation(provider, str(exc)),
            **base,
        )
    except ImportError as exc:
        # litellm raises plain ImportError for some provider deps (e.g. bedrock
        # when boto3 is missing from its runtime). Treat the same as ModuleNotFoundError.
        result = LLMHealthResult(
            status="missing_extras",
            message=f"Missing provider SDK for {provider}: {exc}",
            remediation=_missing_sdk_remediation(provider, str(exc)),
            **base,
        )
    except Exception as exc:
        result = _classify_litellm_error(litellm, exc, provider, base)

    _cached_completion = result
    _cached_completion_at = now
    return result


def _classify_litellm_error(
    litellm_module,
    exc: Exception,
    provider: str,
    base: dict,
) -> LLMHealthResult:
    """Map a litellm exception to an LLMHealthResult status + remediation."""
    exc_name = type(exc).__name__
    exc_msg = str(exc)

    # litellm wraps provider SDK ImportErrors inside its own exceptions — the
    # underlying ModuleNotFoundError is often stringified inside the message.
    lower = exc_msg.lower()
    if ("no module named" in lower) or ("install" in lower and "pip install" in lower):
        return LLMHealthResult(
            status="missing_extras",
            message=f"Missing provider SDK for {provider}: {exc_msg}",
            remediation=_missing_sdk_remediation(provider, exc_msg),
            **base,
        )

    # Walk the known litellm exception hierarchy if available.
    auth_cls = getattr(litellm_module, "AuthenticationError", None)
    if auth_cls and isinstance(exc, auth_cls):
        return LLMHealthResult(
            status="auth_error",
            message=f"Authentication failed for {provider}: {exc_msg}",
            remediation="Check LLM_API_KEY in ~/.mycelium/.env",
            **base,
        )

    bad_req_cls = getattr(litellm_module, "BadRequestError", None)
    if bad_req_cls and isinstance(exc, bad_req_cls):
        return LLMHealthResult(
            status="bad_model",
            message=f"Bad request (likely invalid model string): {exc_msg}",
            remediation=(f"Check LLM_MODEL — expected litellm format like '{provider}/<model-id>'"),
            **base,
        )

    not_found_cls = getattr(litellm_module, "NotFoundError", None)
    if not_found_cls and isinstance(exc, not_found_cls):
        return LLMHealthResult(
            status="bad_model",
            message=f"Model not found: {exc_msg}",
            remediation="Verify LLM_MODEL exists for this provider",
            **base,
        )

    timeout_cls = getattr(litellm_module, "Timeout", None)
    if timeout_cls and isinstance(exc, timeout_cls):
        return LLMHealthResult(
            status="unreachable",
            message=f"Timeout probing {provider}",
            remediation="Check network connectivity from the backend container",
            **base,
        )

    conn_cls = getattr(litellm_module, "APIConnectionError", None)
    if conn_cls and isinstance(exc, conn_cls):
        return LLMHealthResult(
            status="unreachable",
            message=f"Cannot connect to {provider}: {exc_msg}",
            **base,
        )

    return LLMHealthResult(
        status="error",
        message=f"{exc_name}: {exc_msg}",
        **base,
    )
