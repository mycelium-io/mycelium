# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A Pi-backed cognitive brain for mycelium's *internal* agents.

The seam: the SAO mediator's brain is a **persistent, optionally
OpenShell-sandboxed Pi session** — the mediator has no stateless per-call
fallback; Pi is its runtime. This touches neither the NEGMAS loop, the SLIM/HTTP
drive, nor any *user* agent's runtime — Pi is the runtime for our own cognition
agents only; participant agents keep whatever framework they already run.

The mediator injects its brain as a callable
``llm(prompt, *, system="", temperature=…) -> str`` (see ``mediator.py``:
``discover_issues(…, llm=…)`` and ``MediatedNegotiation(…, llm=…)``).
:class:`PiBrain` is a drop-in for that seam whose ``__call__`` drives one
long-lived ``pi -p --session <path> --mode json`` subprocess. Because one
:class:`PiBrain` instance reuses a single ``--session`` file across every call,
the brain accumulates **real durable memory across SAO rounds** — the natural
home for the running state ``MediatedNegotiation`` threads by hand today (the
v1→v2 "the camp counselor needs memory" lesson, now native).

**Synchronous on purpose.** The mediator's brain turns run inside NEGMAS's
``mech.run()`` worker thread, so this is blocking too. We shell out with a
blocking :func:`subprocess.run` bounded by a wall-clock timeout so one hung turn
can never stall the negotiation.

**Serial by construction.** The mediator's turn model is strictly serial (one
``@handle`` at a time), so a single Pi session is never driven concurrently. Do
not share one :class:`PiBrain` across parallel negotiations — build one per run.

**OpenShell sandboxing** is wired as a command-prefix seam (``openshell=True``),
default **off**: ``openshell`` is not guaranteed installed and the sandbox path
is a live-validation step (see the doc's honest caveats). The seam exists from
the start so enabling it live is config, not a code change.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Pi's built-in coding tools (read/bash/edit/write) are useless to a pure
#: interpret-and-broker brain and would let it touch the filesystem — disable
#: them so a mediator turn is cognition only.
_NO_TOOLS = "--no-tools"

#: Pi's streaming API per provider prefix. Anthropic (or an Anthropic-shaped
#: proxy) speaks the Messages API; everything else is assumed OpenAI-compatible
#: (Ollama, vLLM, LM Studio, most gateways).
_ANTHROPIC_API = "anthropic-messages"
_OPENAI_COMPAT_API = "openai-completions"


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


def ensure_custom_provider(
    *,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str | None,
    agent_dir: Path | None = None,
) -> None:
    """Declare a custom-endpoint provider in pi's ``models.json``.

    Pi has **no ``--base-url`` flag** — a custom OpenAI-compatible or Anthropic
    endpoint (Ollama, vLLM, a proxy) is reachable only via a ``providers`` entry
    in ``<agent_dir>/models.json``. mycelium collects ``LLM_BASE_URL`` at install
    time, so we translate it here: upsert one provider entry keyed by *provider*
    and preserve any others the user already configured (merge, not clobber).
    Called before each turn — cheap and idempotent — so the file exists even on a
    fresh container.
    """
    api = _ANTHROPIC_API if provider == "anthropic" else _OPENAI_COMPAT_API
    url = base_url if api == _ANTHROPIC_API else _openai_compat_base_url(base_url)
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
    providers[provider] = {
        "baseUrl": url,
        "api": api,
        # pi requires the field; local servers (Ollama, LM Studio) ignore it.
        "apiKey": api_key or "unused",
        "models": [{"id": model_id}],
    }
    data["providers"] = providers
    models_path.write_text(json.dumps(data, indent=2))
    try:
        models_path.chmod(0o600)
    except OSError:
        logger.debug("could not chmod %s to 0600", models_path)


class PiBrainError(RuntimeError):
    """A ``pi`` invocation failed (missing binary, non-zero exit, timeout).

    The mediator's LLM stages already catch broadly and degrade (a failed
    ``interpret`` becomes a reject, a failed ``broker`` a no-op note), so raising
    here keeps :class:`PiBrain` honest without special-casing the caller.
    """


def _assistant_text(message: dict[str, Any]) -> str:
    """Pull the plain text out of one Pi ``AssistantMessage``.

    Pi's ``--mode json`` messages carry ``content`` as either a bare string or an
    array of parts (``{"type": "text", "text": …}``, tool calls, …). We keep only
    the text parts; tool calls are irrelevant to a ``--no-tools`` brain but the
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
    to stdout must not crash the brain.
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


class PiBrain:
    """A persistent ``pi`` session presented as the mediator's brain callable.

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
        # A custom LLM_BASE_URL (Ollama, vLLM, a proxy) is not a command-line flag
        # in pi — it becomes a ``models.json`` provider entry we generate. Split
        # the "provider/model" ref up front so the entry and the ``--provider``
        # invocation stay consistent. Direct-key providers leave this None.
        self._custom: tuple[str, str] | None = split_provider_model(model) if base_url else None

    def _ensure_provider(self) -> None:
        if self._base_url and self._custom is not None:
            provider, model_id = self._custom
            ensure_custom_provider(
                provider=provider,
                model_id=model_id,
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
        if self._custom is not None:
            # Endpoint + key live in the generated models.json provider entry;
            # address it by its canonical ``provider/model-id`` reference.
            provider, model_id = self._custom
            cmd += ["--provider", provider, "--model", f"{provider}/{model_id}"]
        else:
            cmd += ["--model", self._model]
            if self._api_key:
                cmd += ["--api-key", self._api_key]
        if system:
            cmd += ["--append-system-prompt", system]
        cmd.append(prompt)
        return self._sandbox_wrap(cmd)

    def _sandbox_wrap(self, cmd: list[str]) -> list[str]:
        """Prefix *cmd* with an OpenShell sandbox exec when enabled.

        Best-effort seam: the exact ``openshell`` invocation is unvalidated here
        (the binary isn't installed on the build host), so this is the documented
        shape to confirm during live validation, gated behind ``openshell=False``
        by default. Kept in code so turning the sandbox on is a config flip.
        """
        if not self._openshell:
            return cmd
        return ["openshell", "sandbox", "exec", "--from", "pi", "--", *cmd]

    def __call__(self, prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        """Run one blocking ``pi`` turn against the persistent session.

        ``temperature`` is accepted for signature parity with the mediator's brain
        seam but Pi exposes no temperature flag, so it is intentionally ignored
        (best-effort determinism only).
        """
        del temperature  # no pi CLI knob; kept for brain-callable signature parity
        binary = self._binary
        if shutil.which(binary) is None:
            raise PiBrainError(
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
            )
        except subprocess.TimeoutExpired as exc:
            raise PiBrainError(f"pi turn exceeded {self._timeout_s:.0f}s and was killed") from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise PiBrainError(f"pi exited {completed.returncode}: {stderr[:400]}")
        return parse_pi_json_output(completed.stdout)
