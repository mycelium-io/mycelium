# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A Pi-backed cognitive brain for mycelium's *internal* agents.

A **persistent, optionally OpenShell-sandboxed Pi session** that replaces the SAO
mediator's stateless ``litellm.completion`` brain
(:func:`app.services.mediator.llm_sync`), without touching the NEGMAS loop, the
SLIM drive, or any *user* agent's runtime. Pi is the runtime for our own cognition
agents only; participant agents keep whatever framework they already run.

The mediator injects its brain as a callable
``llm(prompt, *, system="", temperature=…) -> str`` (see ``mediator.py``:
``discover_issues(…, llm=…)`` and ``MediatedNegotiation(…, llm=…)``).
:class:`PiBrain` is a drop-in for that seam whose ``__call__`` drives one
long-lived ``pi -p --session <path> --mode json`` subprocess. Because one
:class:`PiBrain` instance reuses a single ``--session`` file across every call,
the brain accumulates **real durable memory across SAO rounds** — the natural
home for the running state ``MediatedNegotiation`` threads by hand today.

**Synchronous on purpose.** The mediator's LLM turns run inside NEGMAS's
``mech.run()`` worker thread; ``llm_sync`` is blocking and so is this. We shell
out with a blocking :func:`subprocess.run` bounded by a wall-clock timeout so one
hung turn can never stall the negotiation.

**Serial by construction.** The mediator's turn model is strictly serial (one
``@handle`` at a time), so a single Pi session is never driven concurrently. Do
not share one :class:`PiBrain` across parallel negotiations — build one per run.

**OpenShell sandboxing** is wired as a command-prefix seam (``openshell=True``),
default **off**: ``openshell`` is not guaranteed installed. Enabling it live is
config, not a code change.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Pi's built-in coding tools (read/bash/edit/write) are useless to a pure
#: interpret-and-broker brain and would let it touch the filesystem — disable
#: them so a mediator turn is cognition only.
_NO_TOOLS = "--no-tools"


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
                    if not isinstance(message, dict):
                        continue
                    msg = cast("dict[str, Any]", message)
                    if msg.get("role") == "assistant":
                        candidate = _assistant_text(msg)
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
    """A persistent ``pi`` session presented as an ``llm_sync``-compatible callable.

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
        if base_url:
            # Pi has no ``--base-url`` flag (custom endpoints go through
            # ``~/.pi/agent/models.json``), so a mycelium LLM_BASE_URL cannot be
            # forwarded on the command line. Surface it once rather than silently
            # sending the turn to the default endpoint — this is a live-validation
            # rough edge to resolve when wiring a custom provider.
            logger.warning(
                "PiBrain: LLM_BASE_URL=%s is set but pi has no --base-url flag; "
                "configure the endpoint in ~/.pi/agent/models.json instead",
                base_url,
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
            "--model",
            self._model,
        ]
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

        ``temperature`` is accepted for signature-compatibility with
        :func:`app.services.mediator.llm_sync` but Pi exposes no temperature flag,
        so it is intentionally ignored (best-effort determinism only).
        """
        del temperature  # no pi CLI knob; kept for llm_sync signature parity
        binary = self._binary
        if shutil.which(binary) is None:
            raise PiBrainError(
                f"`{binary}` not found on PATH — install Pi (earendil-works/pi) "
                "or set ALIGNER_BRAIN=litellm."
            )
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
