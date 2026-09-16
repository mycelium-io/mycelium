"""Environment detection — probes backend and SLIM node health."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from libs.mycelium_api import MyceliumAPI

log = logging.getLogger(__name__)


class EnvironmentInfo:
    """Reachability and configuration state for SLIM-native Mycelium."""

    def __init__(self):
        self.backend_reachable: bool = False
        self.backend_status: Optional[str] = None
        self.backend_health: dict = {}
        self.slim_reachable: bool = False
        self.slim_endpoint: Optional[str] = None
        self.llm_available: bool = False
        self.llm_detail: Optional[str] = None

    @property
    def skip_llm_tests(self) -> bool:
        return not self.llm_available

    @property
    def coordination_ready(self) -> bool:
        """Both backend and SLIM node must be up for coordination tests."""
        return self.backend_reachable and self.slim_reachable

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend_reachable": self.backend_reachable,
            "backend_status": self.backend_status,
            "slim_reachable": self.slim_reachable,
            "slim_endpoint": self.slim_endpoint,
            "llm_available": self.llm_available,
            "llm_detail": self.llm_detail,
        }


_LLM_FAILURE_STATUSES = frozenset({
    "auth_error", "unavailable", "error", "misconfigured", "not_configured",
})


def detect_environment(backend: MyceliumAPI) -> EnvironmentInfo:
    """Probe backend and SLIM node; return a populated EnvironmentInfo."""
    env = EnvironmentInfo()

    # ── Backend health ────────────────────────────────────────────────────
    health = backend.health_json()
    if health:
        env.backend_reachable = True
        env.backend_status = "ok"
        env.backend_health = health

        llm_status = health.get("llm")
        if isinstance(llm_status, dict):
            status_val = llm_status.get("status", "")
            env.llm_available = bool(status_val) and status_val not in _LLM_FAILURE_STATUSES
            env.llm_detail = (
                f"status={status_val} model={llm_status.get('model', '?')} "
                f"base_url={'set' if llm_status.get('base_url') else 'NOT SET'}"
            )
        elif isinstance(llm_status, str):
            env.llm_available = bool(llm_status) and llm_status not in _LLM_FAILURE_STATUSES
            env.llm_detail = f"status={llm_status}"
        else:
            env.llm_available = False
            env.llm_detail = f"unexpected llm type: {type(llm_status).__name__}"

        log.info(
            "Backend: reachable=True llm=%s (%s)",
            "available" if env.llm_available else "unavailable",
            env.llm_detail,
        )
        _check_llm_env_vars(env)

        # ── SLIM node reachability ─────────────────────────────────────────
        # SLIM node may be on a Docker network (e.g. mycelium-slim:46357),
        # not directly reachable from the host. Use backend's reported status.
        coord = health.get("coordination") or health.get("slim") or health.get("network") or {}
        if isinstance(coord, dict):
            env.slim_endpoint = coord.get("endpoint") or coord.get("node_endpoint")
            slim_enabled = coord.get("slim_enabled", False)
            # Backend reports SLIM as up if slim_enabled and no error state
            env.slim_reachable = bool(slim_enabled and env.slim_endpoint)
        # Fallback: direct probe if backend doesn't report coordination status
        if not env.slim_reachable and not env.slim_endpoint:
            env.slim_reachable, env.slim_endpoint = _probe_slim_node()
    else:
        env.backend_status = "unreachable"
        log.warning("Backend unreachable at %s", backend.base_url)

    log.info(
        "SLIM node: reachable=%s endpoint=%s",
        env.slim_reachable,
        env.slim_endpoint or "unknown",
    )
    return env


def _probe_slim_node() -> tuple[bool, Optional[str]]:
    """Try to reach the SLIM node at the configured endpoint."""
    endpoint = os.environ.get("MYCELIUM_SLIM_ENDPOINT", "http://localhost:46357")
    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status < 500, endpoint
    except urllib.error.HTTPError as e:
        # Any HTTP response (even 4xx) means the node is listening
        return e.code < 500, endpoint
    except Exception:
        return False, endpoint


def _check_llm_env_vars(env: EnvironmentInfo) -> None:
    key_set = bool(os.environ.get("LLM_API_KEY"))
    url_set = bool(os.environ.get("LLM_BASE_URL"))
    if key_set and not url_set:
        log.warning(
            "LLM_API_KEY is set but LLM_BASE_URL is empty — backend may use wrong provider"
        )
    if not key_set:
        log.info("LLM_API_KEY not set on host; LLM availability depends on backend config")
