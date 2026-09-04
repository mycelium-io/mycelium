# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A Pi-backed LLM session for mycelium's *internal* agents.

The seam: the SAO mediator's LLM session is a **persistent, optionally
OpenShell-sandboxed Pi session** — the mediator has no stateless per-call
fallback; Pi is its runtime. This touches neither the NEGMAS loop, the SLIM/HTTP
drive, nor any *user* agent's runtime — Pi is the runtime for our own cognition
agents only; participant agents keep whatever framework they already run.

The mediator injects its LLM session as a callable
``llm(prompt, *, system="", temperature=…) -> str`` (see ``mediator.py``:
``discover_issues(…, llm=…)`` and ``MediatedNegotiation(…, llm=…)``).
:class:`PiSession` is a drop-in for that seam whose ``__call__`` drives one
long-lived ``pi -p --session <path> --mode json`` subprocess. Because one
:class:`PiSession` instance reuses a single ``--session`` file across every call,
the LLM session accumulates **real durable memory across SAO rounds** — the natural
home for the running state ``MediatedNegotiation`` threads by hand today.

**Synchronous on purpose.** The mediator's LLM session turns run inside NEGMAS's
``mech.run()`` worker thread, so this is blocking too. We shell out with a
blocking :func:`subprocess.run` bounded by a wall-clock timeout so one hung turn
can never stall the negotiation.

**Serial by construction.** The mediator's turn model is strictly serial (one
``@handle`` at a time), so a single Pi session is never driven concurrently. Do
not share one :class:`PiSession` across parallel negotiations — build one per run.

**OpenShell sandboxing** is wired as a command-prefix seam (``openshell=True``),
default **off**: ``openshell`` is not guaranteed installed and the sandbox path
is a live-validation step (see the doc's honest caveats). Controlled by
config, no code change required.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Pi's built-in coding tools (read/bash/edit/write) are useless to a pure
#: interpret-and-broker session and would let it touch the filesystem — disable
#: them so a mediator turn is cognition only.
_NO_TOOLS = "--no-tools"

#: A non-built-in endpoint is assumed OpenAI-compatible (Ollama, vLLM, LM Studio,
#: most gateways) — pi's most widely compatible streaming API.
_OPENAI_COMPAT_API = "openai-completions"

#: Providers pi ships built-in (with a full, capability-annotated model catalog).
#: A base URL for one of these is a *redirect* (baseUrl-only override that keeps
#: the real catalog), never a replacement — see :func:`ensure_provider_config`.
_PI_BUILTIN_PROVIDERS = frozenset(
    {
        "amazon-bedrock",
        "anthropic",
        "azure-openai-responses",
        "openai",
        "openai-codex",
        "google",
        "google-gemini-cli",
        "google-antigravity",
        "google-vertex",
        "github-copilot",
        "openrouter",
        "vercel-ai-gateway",
        "xai",
        "groq",
        "cerebras",
        "zai",
        "mistral",
        "minimax",
        "minimax-cn",
        "huggingface",
        "opencode",
        "opencode-go",
        "kimi-coding",
    }
)


def split_provider_model(model: str) -> tuple[str, str]:
    """Split a ``provider/model-id`` string into ``(provider, model_id)``.

    A bare id (no ``/``) has no provider prefix, so it is filed under ``custom``.
    """
    ref = model.strip()
    if "/" in ref:
        provider, model_id = ref.split("/", 1)
        provider = provider.strip() or "custom"
        model_id = model_id.strip()
        if model_id:
            return provider, model_id
    return "custom", ref


def provider_is_builtin(provider: str) -> bool:
    """True when *provider* is one pi ships with a built-in model catalog."""
    return provider in _PI_BUILTIN_PROVIDERS


#: A built-in provider's own public API host(s). A ``LLM_BASE_URL`` that merely
#: names one of these is a no-op — pi already routes there — so we must NOT write
#: a models.json override for it (that both is redundant and, on a host with the
#: user's real ~/.pi + OAuth, conflicts and hangs pi). Only a genuinely different
#: host (a proxy) warrants an override.
_PROVIDER_STANDARD_HOSTS: dict[str, frozenset[str]] = {
    "anthropic": frozenset({"api.anthropic.com"}),
    "openai": frozenset({"api.openai.com"}),
    "openrouter": frozenset({"openrouter.ai"}),
    "google": frozenset({"generativelanguage.googleapis.com"}),
    "groq": frozenset({"api.groq.com"}),
    "mistral": frozenset({"api.mistral.ai"}),
    "xai": frozenset({"api.x.ai"}),
    "cerebras": frozenset({"api.cerebras.ai"}),
}


def is_standard_endpoint(provider: str, base_url: str) -> bool:
    """True when *base_url* just names *provider*'s own public endpoint (not a proxy)."""
    hosts = _PROVIDER_STANDARD_HOSTS.get(provider)
    if not hosts:
        return False
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host.lower() in hosts


def _pi_agent_dir() -> Path:
    """Pi's agent config dir — mirrors pi's ``getAgentDir()``.

    ``$PI_CODING_AGENT_DIR`` (with the same leading-``~`` expansion pi does) when
    set, else ``~/.pi/agent``. ``models.json`` lives directly inside it.
    """
    override = os.getenv("PI_CODING_AGENT_DIR")
    if not override:
        return Path.home() / ".pi" / "agent"
    if override.startswith("~"):
        return Path(str(Path.home()) + override[1:])
    return Path(override)


def _openai_compat_base_url(base_url: str) -> str:
    """Ensure an OpenAI-compatible base URL ends in ``/v1`` (pi wants the full path)."""
    trimmed = base_url.rstrip("/")
    return trimmed if trimmed.endswith("/v1") else f"{trimmed}/v1"


def _safe_prompt_arg(prompt: str) -> str:
    """Neutralize a prompt that pi's arg parser would mis-read as a flag/file.

    Pi treats a positional argument starting with ``@`` as an ``@file`` mention
    (it tries to *read a file* named after the prompt) and one starting with
    ``-`` as an option (see pi ``cli/args.js``). The session feeds arbitrary text
    — agent prose, opening positions, a mediator turn that opens with
    ``@handle`` — as that positional, so a leading ``@`` or ``-`` would break the
    turn. A single leading space makes pi parse it as a message; the model does
    not care about one space of leading whitespace. Only the *leading* character
    matters (mid-prompt ``@handle`` is parsed as text), so this is sufficient.
    """
    return f" {prompt}" if prompt[:1] in ("@", "-") else prompt


def ensure_provider_config(
    *,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str | None,
    agent_dir: Path | None = None,
) -> None:
    """Translate a mycelium ``LLM_BASE_URL`` into a pi ``models.json`` entry.

    Pi has **no ``--base-url`` flag** — a base URL reaches pi only via a
    ``providers`` entry in ``<agent_dir>/models.json``. Two shapes, by provider:

    - **Built-in provider** (anthropic, openai, openrouter, …): a *baseUrl-only
      override* that redirects the endpoint while **keeping pi's real,
      capability-annotated model catalog**. This is the common case (an install
      that sets ``LLM_BASE_URL`` to the standard endpoint, or to a proxy in front
      of it). The key still rides the ``--api-key`` flag, and the model is
      addressed by its built-in id — so a bare ``{id}`` stub never shadows the
      real model definition.
    - **Custom provider** (Ollama, vLLM, a private OpenAI-compatible server): a
      full entry (``baseUrl`` + ``api`` + ``apiKey`` + a one-model list), since
      pi has no catalog for it.

    Existing providers the user configured are preserved (merge, not clobber).
    Called before each turn — cheap and idempotent — so the file exists even on a
    fresh container.
    """
    if provider_is_builtin(provider):
        # Redirect only; pi keeps its own model catalog + capabilities.
        entry: dict[str, Any] = {"baseUrl": base_url}
    else:
        entry = {
            "baseUrl": _openai_compat_base_url(base_url),
            "api": _OPENAI_COMPAT_API,
            # pi requires the field; local servers (Ollama, LM Studio) ignore it.
            "apiKey": api_key or "unused",
            "models": [{"id": model_id}],
        }

    models_path = (agent_dir or _pi_agent_dir()) / "models.json"
    models_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if models_path.exists():
        try:
            loaded = json.loads(models_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("pi models.json at %s unreadable; rewriting entry", models_path)
        else:
            if isinstance(loaded, dict):
                data = loaded
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    providers[provider] = entry
    data["providers"] = providers
    models_path.write_text(json.dumps(data, indent=2))
    try:
        models_path.chmod(0o600)
    except OSError:
        logger.debug("could not chmod %s to 0600", models_path)


class PiSessionError(RuntimeError):
    """A ``pi`` invocation failed (missing binary, non-zero exit, timeout)."""


def _assistant_text(message: dict[str, Any]) -> str:
    """Pull the plain text out of one Pi ``AssistantMessage``.

    Pi's ``--mode json`` messages carry ``content`` as either a bare string or an
    array of parts (``{"type": "text", "text": …}``, tool calls, …). We keep only
    the text parts; tool calls are irrelevant to a ``--no-tools`` session but the
    guard is cheap and future-proof.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return "".join(parts)


def parse_pi_json_output(stdout: str) -> str:
    """Extract the final assistant text from a ``pi --mode json`` event stream.

    Each stdout line is one JSON event (``docs/json.md``). The authoritative final
    answer is the last assistant message in the terminal ``agent_end`` event; we
    also fold ``message_end``/``turn_end`` assistant messages so a truncated
    stream (no ``agent_end``) still yields the latest turn. Non-JSON lines and
    non-dict events are skipped defensively — a future Pi build adding a log line
    to stdout must not crash the session.
    """
    text = ""
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "agent_end":
            messages = event.get("messages")
            if isinstance(messages, list):
                for message in reversed(messages):
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        candidate = _assistant_text(message)
                        if candidate.strip():
                            text = candidate
                        break
        elif etype in ("message_end", "turn_end"):
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                candidate = _assistant_text(message)
                if candidate.strip():
                    text = candidate
    return text.strip()


class PiSession:
    """A persistent ``pi`` session presented as the mediator's LLM callable.

    One instance == one ``--session`` file == one negotiation's memory. Construct
    it per :meth:`app.services.aligner.AlignerEngine.mediate` run and pass it as
    ``llm=`` into ``discover_issues`` and ``MediatedNegotiation``.
    """

    def __init__(
        self,
        *,
        session_path: Path,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        binary: str = "pi",
        timeout_s: float = 120.0,
        openshell: bool = False,
    ) -> None:
        self._session_path = session_path
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._binary = binary
        self._timeout_s = timeout_s
        self._openshell = openshell
        # A LLM_BASE_URL is not a pi command-line flag — it becomes a models.json
        # provider entry we generate. Endpoint mode:
        #   "direct"  — no base URL; --model/--api-key straight through.
        #   "builtin" — base URL for a built-in provider; redirect its endpoint
        #               but keep pi's model catalog (--model/--api-key unchanged).
        #   "custom"  — base URL for a non-built-in provider (Ollama, a proxy);
        #               address it via --provider, key rides in models.json.
        self._provider, self._model_id = split_provider_model(model)
        if not base_url:
            self._endpoint_mode = "direct"
        elif provider_is_builtin(self._provider):
            # A base URL that just names the provider's own endpoint is a no-op —
            # stay direct (no override written). Only a real proxy → "builtin".
            self._endpoint_mode = (
                "direct" if is_standard_endpoint(self._provider, base_url) else "builtin"
            )
        else:
            self._endpoint_mode = "custom"

    def _ensure_provider(self) -> None:
        if self._base_url and self._endpoint_mode != "direct":
            ensure_provider_config(
                provider=self._provider,
                model_id=self._model_id,
                base_url=self._base_url,
                api_key=self._api_key,
            )

    def _build_command(self, prompt: str, system: str) -> list[str]:
        cmd = [
            self._binary,
            "--print",
            "--mode",
            "json",
            "--session",
            str(self._session_path),
            _NO_TOOLS,
        ]
        if self._endpoint_mode == "custom":
            # Endpoint + key live in the generated models.json provider entry;
            # address it by its canonical ``provider/model-id`` reference.
            cmd += ["--provider", self._provider, "--model", f"{self._provider}/{self._model_id}"]
        else:
            # direct or builtin-redirect: pi keeps the real model + the key flag.
            cmd += ["--model", self._model]
            if self._api_key:
                cmd += ["--api-key", self._api_key]
        if system:
            cmd += ["--append-system-prompt", system]
        cmd.append(_safe_prompt_arg(prompt))
        return self._sandbox_wrap(cmd)

    def _sandbox_wrap(self, cmd: list[str]) -> list[str]:
        """Prefix *cmd* with an OpenShell sandbox exec when enabled."""
        if not self._openshell:
            return cmd
        return ["openshell", "sandbox", "exec", "--from", "pi", "--", *cmd]

    def __call__(self, prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        """Run one blocking ``pi`` turn against the persistent session.

        ``temperature`` is accepted for signature parity with the mediator's LLM session
        seam but Pi exposes no temperature flag, so it is intentionally ignored
        (best-effort determinism only).
        """
        del temperature  # no pi CLI knob; kept for LLM-callable signature parity
        binary = self._binary
        if shutil.which(binary) is None:
            raise PiSessionError(
                f"`{binary}` not found on PATH — the aligner's mediator runs on Pi; "
                "install Pi (earendil-works/pi) or set ALIGNER_PI_BINARY to its path."
            )
        self._ensure_provider()
        cmd = self._build_command(prompt, system)
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
                # pi reads piped stdin (readPipedStdin) whenever stdin is not a
                # TTY — which is exactly our case: the backend, the daemon, and
                # any container run pi with a non-TTY stdin. Without this it
                # blocks reading stdin that never arrives and every turn hangs to
                # the timeout. DEVNULL gives it immediate EOF so it uses the
                # prompt arg.
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise PiSessionError(f"pi turn exceeded {self._timeout_s:.0f}s and was killed") from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise PiSessionError(f"pi exited {completed.returncode}: {stderr[:400]}")
        return parse_pi_json_output(completed.stdout)
