"""
LLM health checking: key format validation, masked key hints, and
zero-cost provider probes using read-only model-list endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

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


class _ProbeBase(TypedDict):
    model: str
    configured: bool
    key_hint: str | None
    key_required: bool


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
    api_key = settings.LLM_API_KEY or ""
    has_key = bool(api_key)
    has_base_url = bool(settings.LLM_BASE_URL)
    key_hint = mask_key(api_key) if has_key else None

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
        fmt_warning = validate_key_format(api_key, provider)
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
    base: _ProbeBase = {
        "model": model,
        "configured": True,
        "key_hint": config.key_hint,
        "key_required": config.key_required,
    }

    if provider == "ollama" or (settings.LLM_BASE_URL and not settings.LLM_API_KEY):
        return await _probe_ollama(base)

    # LiteLLM and other OpenAI-compatible proxies: key is valid only at the proxy,
    # not at api.anthropic.com — probe the custom base URL.
    if settings.LLM_BASE_URL and settings.LLM_API_KEY:
        return await _probe_openai_compatible_proxy(base)

    endpoint = _MODEL_LIST_ENDPOINTS.get(provider)
    if endpoint:
        return await _probe_api_key(endpoint, provider, base)

    return _result(
        base,
        status="unchecked",
        message="Key validation not supported for this provider. Key is configured but could not be verified.",
    )


def _result(
    base: _ProbeBase,
    *,
    status: str,
    message: str,
    remediation: str | None = None,
) -> LLMHealthResult:
    return LLMHealthResult(
        status=status,
        message=message,
        remediation=remediation,
        model=base["model"],
        configured=base["configured"],
        key_hint=base["key_hint"],
        key_required=base["key_required"],
    )


async def _probe_openai_compatible_proxy(base: _ProbeBase) -> LLMHealthResult:
    """Probe LLM_BASE_URL using OpenAI-compatible GET /v1/models (LiteLLM, etc.)."""
    raw_base = settings.LLM_BASE_URL or ""
    base_url = raw_base.rstrip("/")
    models_url = f"{base_url}/v1/models"
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(models_url, headers=headers)
        except httpx.ConnectError:
            return _result(
                base, status="unreachable", message=f"Cannot connect to LLM proxy at {base_url}"
            )
        except httpx.TimeoutException:
            return _result(
                base, status="unreachable", message=f"Timeout connecting to LLM proxy at {base_url}"
            )

        if resp.status_code == 200:
            return _result(base, status="ok", message="API key is valid")
        if resp.status_code in (401, 403):
            return _result(base, status="auth_error", message="API key is invalid or expired")
        return _result(
            base,
            status="unreachable",
            message=f"LLM proxy returned unexpected status {resp.status_code}",
        )


async def _probe_api_key(endpoint: str, provider: str, base: _ProbeBase) -> LLMHealthResult:
    """Probe OpenAI or Anthropic via their free model-list endpoint."""
    headers: dict[str, str] = {}
    api_key = settings.LLM_API_KEY or ""
    if provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(endpoint, headers=headers)
        except httpx.ConnectError:
            return _result(base, status="unreachable", message=f"Cannot connect to {provider} API")
        except httpx.TimeoutException:
            return _result(
                base, status="unreachable", message=f"Timeout connecting to {provider} API"
            )

    if resp.status_code == 200:
        return _result(base, status="ok", message="API key is valid")
    if resp.status_code in (401, 403):
        return _result(base, status="auth_error", message="API key is invalid or expired")
    return _result(
        base,
        status="unreachable",
        message=f"{provider} API returned unexpected status {resp.status_code}",
    )


async def _probe_ollama(base: _ProbeBase) -> LLMHealthResult:
    """Connectivity check for Ollama (no key required)."""
    base_url = (settings.LLM_BASE_URL or "http://localhost:11434").rstrip("/")
    tags_url = f"{base_url}/api/tags"

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            resp = await client.get(tags_url)
        except httpx.ConnectError:
            return _result(
                base, status="unreachable", message=f"Cannot connect to Ollama at {base_url}"
            )
        except httpx.TimeoutException:
            return _result(
                base, status="unreachable", message=f"Timeout connecting to Ollama at {base_url}"
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


# ── Completion probe ───────────────────────────────────────────────────
#
# probe_provider() uses provider-specific model-list endpoints (free, zero-token)
# but reports "unchecked" outside openai/anthropic/ollama/openai-compatible
# proxies — so a broken Bedrock or Vertex config reads green until the first
# real inference.
#
# probe_completion() runs a real one-shot ``pi`` turn — the same runtime the
# aligner's LLM session and the plan compiler use — catching a missing/broken ``pi``
# binary, bad model strings, and auth errors at the true endpoint.


_cached_completion: LLMHealthResult | None = None
_cached_completion_at: float = 0.0


async def probe_completion() -> LLMHealthResult:
    """Level C: real completion probe via a one-shot ``pi`` turn.

    Surfaces failure modes that ``probe_provider()`` cannot:

    1. A missing or non-functional ``pi`` binary — reported as ``error`` with an
       install hint.
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

    base: _ProbeBase = {
        "model": model,
        "configured": True,
        "key_hint": config_result.key_hint,
        "key_required": config_result.key_required,
    }

    probe_error = False
    try:
        await asyncio.wait_for(asyncio.to_thread(_pi_ping, model), timeout=_PROBE_TIMEOUT + 5)
        result = _result(base, status="ok", message="Completion probe succeeded")
    except TimeoutError:
        probe_error = True
        result = _result(
            base,
            status="unreachable",
            message=f"Timeout probing {provider}",
            remediation="Check network connectivity from the backend container",
        )
    except Exception as exc:  # a probe classifies every failure, never propagates
        probe_error = True  # noqa: F841
        result = _classify_pi_error(exc, provider, base)
    finally:
        # PiSession inside _pi_ping already records via record_llm_call(operation="health_probe").
        # This outer timing wrapper only adds elapsed wall-clock to the call that was already
        # recorded, causing a double-count. Remove it — PiSession is the single source.
        pass

    _cached_completion = result
    _cached_completion_at = now
    return result


def _pi_ping(model: str) -> str:
    """Run a blocking pi "ping" completion probe."""
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    llm_session = PiSession(
        session_path=session_dir / "health-probe.jsonl",
        model=model,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=float(_PROBE_TIMEOUT),
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="health_probe",
    )
    return llm_session("ping")


def _classify_pi_error(exc: Exception, provider: str, base: _ProbeBase) -> LLMHealthResult:
    """Map a ``pi`` probe failure to an LLMHealthResult status + remediation.

    ``PiSession`` raises ``PiSessionError`` with the process stderr embedded; we
    classify off that text since ``pi`` has no typed exception hierarchy to walk.
    """
    exc_msg = str(exc)
    lower = exc_msg.lower()

    if "not found on path" in lower:
        return _result(
            base,
            status="error",
            message=f"pi binary unavailable: {exc_msg}",
            remediation="Install Pi (earendil-works/pi) in the backend container "
            "or set ALIGNER_PI_BINARY to its path.",
        )
    if (
        "auth" in lower
        or "api key" in lower
        or "api-key" in lower
        or "401" in lower
        or "403" in lower
    ):
        return _result(
            base,
            status="auth_error",
            message=f"Authentication failed for {provider}: {exc_msg}",
            remediation="Check LLM_API_KEY in ~/.mycelium/.env",
        )
    if (
        "not found" in lower
        or "unknown model" in lower
        or "no such model" in lower
        or "404" in lower
    ):
        return _result(
            base,
            status="bad_model",
            message=f"Model not found or invalid: {exc_msg}",
            remediation=f"Check LLM_MODEL — expected provider/model like '{provider}/<model-id>'",
        )
    if "timeout" in lower or "timed out" in lower or "exceeded" in lower:
        return _result(
            base,
            status="unreachable",
            message=f"Timeout probing {provider}",
            remediation="Check network connectivity from the backend container",
        )
    if "connect" in lower or "network" in lower or "unreachable" in lower:
        return _result(
            base, status="unreachable", message=f"Cannot connect to {provider}: {exc_msg}"
        )

    return _result(base, status="error", message=f"{type(exc).__name__}: {exc_msg}")
