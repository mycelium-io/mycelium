#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Point real agent-harness binaries at a real room and report what happened.

Mycelium's resident model asks one thing of a harness: hold a reasoning turn
non-interactively. ``mycelium await --loop --exec <cmd>`` loops await → reason →
respond, and ``<cmd>`` is the harness. That claim is only worth making about a
binary someone has actually run, so this grades each family on a ladder and stops
at the first rung it cannot climb:

===============  ==========================================================
``binary``       on PATH, and its version probe exits 0
``auth``         an auth env var is set, or a cached-login artifact exists
``oneshot``      one headless turn echoes a nonce back on stdout
``participate``  a resident loop answers an ``@``-mention in a live room
===============  ==========================================================

Every rung is PASS, FAIL, or SKIP-with-a-reason, and a SKIP is never a FAIL: a
runner with no Kiro binary has learned nothing about Kiro. That is what makes this
safe to run per-PR — it reports the truth about the machine it is on.

``auth`` is **advisory** and never blocks the rung above it. Harnesses authenticate
in ways no probe can enumerate (a managed host may inject a token over a file
descriptor), so an undetected credential must not be reported as a broken harness.
When ``auth`` came back unknown and ``oneshot`` then fails, the failure is annotated
as probably-unauthenticated rather than guessed at up front.

``participate`` needs a manifest, so it needs a registered adapter. For a family
with no integration yet it reports ``needs-adapter``, which is exactly the gap the
integration closes; ``oneshot`` still grades, so the harness is de-risked before a
line of adapter code is written.

Usage::

    uv run --project mycelium-cli python scripts/harness_conformance.py
    uv run --project mycelium-cli python scripts/harness_conformance.py --family codex
    uv run --project mycelium-cli python scripts/harness_conformance.py \
        --max-level oneshot --json-report report.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from mycelium.integrations.harness_specs import HARNESS_SPECS, PROMPT_SLOT, HarnessSpec
from mycelium.protocol import AGENT_ADAPTERS

#: The ladder, in order.
LEVELS: tuple[str, ...] = ("binary", "auth", "oneshot", "participate")

#: Rungs that must pass before the next one is attempted. ``auth`` is absent on
#: purpose: it informs the report, it does not gate it.
BLOCKING: frozenset[str] = frozenset({"binary", "oneshot"})

Status = Literal["pass", "fail", "skip"]

#: How long one headless turn may take before we call it hung. Harnesses that
#: reason for minutes are normal; a harness that never returns is the failure.
ONESHOT_TIMEOUT_S = 240
#: How long to wait for a resident loop's reply to land in the transcript.
PARTICIPATE_TIMEOUT_S = 300


@dataclass
class Rung:
    level: str
    status: Status
    detail: str
    seconds: float = 0.0


@dataclass
class Report:
    family: str
    label: str
    binary: str
    adapter_status: str
    rungs: list[Rung]

    @property
    def highest_pass(self) -> str:
        """The highest *blocking* rung that passed — what this harness is proven to do.

        ``auth`` is excluded: it is advisory, and a harness whose credentials the
        probe merely happened to recognise has not been shown to reason.
        """
        passed = [r.level for r in self.rungs if r.status == "pass" and r.level != "auth"]
        return passed[-1] if passed else "none"

    @property
    def failed(self) -> bool:
        return any(r.status == "fail" for r in self.rungs)


# ── the exec handler ─────────────────────────────────────────────────────────
#
# This is the generic bridge between a turn and a harness, and it is deliberately
# harness-agnostic: it reads the turn from the env vars `mycelium await --exec`
# exports, runs the argv template it is handed, and posts stdout back with
# `mycelium respond`. Nothing in it knows which harness it is driving, which is
# the point — an adapter would ship exactly this and vary only HARNESS_ARGV.

_HANDLER = '''#!/usr/bin/env python3
"""Turn → harness → respond. Argv template arrives as HARNESS_ARGV (JSON)."""
import json, os, subprocess, sys

sys.stdin.read()  # drain the turn JSON; the env vars carry the same fields

room = os.environ["MYCELIUM_ROOM"]
handle = os.environ["MYCELIUM_HANDLE"]
prompt = os.environ.get("MYCELIUM_PROMPT", "")
argv = [prompt if a == "{slot}" else a for a in json.loads(os.environ["HARNESS_ARGV"])]

try:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout={timeout})
    answer = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
except Exception as exc:  # noqa: BLE001 - the handler must always answer
    answer, err = "", f"{{type(exc).__name__}}: {{exc}}"

if not answer:
    answer = f"harness produced no output ({{err[:400]}})"

subprocess.run(
    ["mycelium", "respond", "--room", room, "--handle", handle, answer], check=False
)
'''


def _write_handler(workspace: Path) -> Path:
    handler = workspace / "harness_turn.py"
    handler.write_text(
        _HANDLER.format(slot=PROMPT_SLOT, timeout=ONESHOT_TIMEOUT_S), encoding="utf-8"
    )
    handler.chmod(0o755)
    return handler


# ── rungs ────────────────────────────────────────────────────────────────────


def _run(argv: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - argv list from the spec table, never a shell string
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def probe_binary(spec: HarnessSpec) -> Rung:
    if not spec.is_harness:
        return Rung("binary", "skip", f"not an agent harness — {spec.note.split('.')[0]}")
    path = shutil.which(spec.binary)
    if path is None:
        return Rung("binary", "skip", f"{spec.binary} not on PATH ({spec.install_hint})")
    if not spec.version_argv:
        return Rung("binary", "pass", path)
    started = time.monotonic()
    try:
        proc = _run([spec.binary, *spec.version_argv], timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return Rung("binary", "fail", f"version probe failed: {exc}", time.monotonic() - started)
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        return Rung(
            "binary",
            "fail",
            f"`{spec.binary} --version` exited {proc.returncode}: {detail}",
            elapsed,
        )
    return Rung("binary", "pass", f"{path} — {(proc.stdout or '').strip()[:80]}", elapsed)


def probe_auth(spec: HarnessSpec) -> Rung:
    present = [name for name in spec.auth.env_vars if os.environ.get(name)]
    if present:
        return Rung("auth", "pass", f"env: {', '.join(present)}")
    cached = [p for p in spec.auth.credential_paths if (Path.home() / p).exists()]
    if cached:
        return Rung("auth", "pass", f"cached login: ~/{cached[0]}")
    if not spec.auth.unattended:
        return Rung(
            "auth",
            "skip",
            f"undetected — {spec.label} publishes no API-key env var, so an unattended "
            f"runner cannot authenticate at all (run `{spec.auth.login_command}` on a "
            "developer machine and the cached login is reused)",
        )
    wanted = " or ".join(spec.auth.env_vars)
    return Rung(
        "auth",
        "skip",
        f"undetected: no {wanted} and no cached login (`{spec.auth.login_command}`). "
        "Trying the turn anyway — credentials can arrive by routes a probe cannot see.",
    )


def probe_oneshot(spec: HarnessSpec, workspace: Path, *, auth_detected: bool) -> Rung:
    """One headless turn must echo a nonce back — proof it reasoned and printed."""
    nonce = f"MYCELIUM-OK-{uuid.uuid4().hex[:8].upper()}"
    prompt = (
        f"Reply with exactly this token and nothing else, no punctuation, no explanation: {nonce}"
    )
    argv = spec.render_argv(prompt)
    started = time.monotonic()
    try:
        proc = _run(argv, timeout=ONESHOT_TIMEOUT_S, cwd=workspace)
    except subprocess.TimeoutExpired:
        return Rung(
            "oneshot",
            "fail",
            f"no answer within {ONESHOT_TIMEOUT_S}s — `{' '.join(argv[:3])} …` hung",
            time.monotonic() - started,
        )
    except OSError as exc:
        return Rung("oneshot", "fail", f"could not run {spec.binary}: {exc}")
    elapsed = time.monotonic() - started
    stdout = proc.stdout or ""
    if nonce in stdout:
        return Rung("oneshot", "pass", f"echoed the nonce in {elapsed:.1f}s", elapsed)
    tail = (proc.stderr or stdout).strip().splitlines()
    hint = tail[-1][:200] if tail else "(no output)"
    suspect = "" if auth_detected else " (auth was undetected; likely unauthenticated)"
    return Rung(
        "oneshot",
        "fail",
        f"exit {proc.returncode}, nonce absent from stdout: {hint}{suspect}",
        elapsed,
    )


def _hub_reachable() -> bool:
    if shutil.which("mycelium") is None:
        return False
    try:
        return _run(["mycelium", "room", "ls"], timeout=45).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _slim_node() -> tuple[str, bool]:
    """Return the configured SLIM node endpoint and whether it accepts a connection.

    A room is a SLIM group channel, so with no node the hub cannot provision the
    channel and ``await`` returns an empty turn forever. Probing up front turns a
    seven-minute silent timeout into an immediate, correct SKIP.
    """
    from mycelium.config import MyceliumConfig

    endpoint = MyceliumConfig.load().slim.node_endpoint
    parsed = urlparse(endpoint)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 46357
    try:
        with socket.create_connection((host, port), timeout=5):
            return endpoint, True
    except OSError:
        return endpoint, False


def _await_banner(loop: subprocess.Popen, timeout: int = 60) -> bool:
    """Block until the resident loop says it is awaiting, so the mention is not
    posted into the gap before the handle's delivery cursor is anchored."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if loop.stdout is None or loop.poll() is not None:
            return False
        line = loop.stdout.readline()
        if not line:
            continue
        if "awaiting" in line:
            return True
    return False


def _reply_landed(room: str, handle: str, nonce: str) -> bool:
    """True once a message from *handle* carrying *nonce* is in the transcript."""
    try:
        proc = _run(
            [
                "mycelium",
                "--json",
                "room",
                "messages",
                room,
                "--sender",
                handle,
                "--limit",
                "10",
            ],
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        return False
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return any(nonce in (m.get("content") or "") for m in payload.get("messages", []))


def probe_participate(spec: HarnessSpec, workspace: Path) -> Rung:
    """The real thing: a resident loop answers an ``@``-mention in a live room."""
    if spec.family not in AGENT_ADAPTERS:
        return Rung(
            "participate",
            "skip",
            f"needs-adapter: no integration for '{spec.family}', so no manifest can be "
            "registered and the hub refuses the handle. This is the gap an adapter closes.",
        )
    if not _hub_reachable():
        return Rung("participate", "skip", "no reachable hub (`mycelium room ls` failed)")
    endpoint, node_up = _slim_node()
    if not node_up:
        return Rung(
            "participate",
            "skip",
            f"no SLIM node at {endpoint} — a room is a SLIM group channel, so the hub "
            "cannot provision one and `await` never serves a turn. Start one with "
            "`mycelium hub host` or the `slim` compose service.",
        )

    suffix = uuid.uuid4().hex[:6]
    room = f"harness-conformance-{spec.family.replace('_', '-')}-{suffix}"
    handle = f"conf-{spec.family.replace('_', '-')}-{suffix}"
    nonce = f"MYCELIUM-PONG-{suffix.upper()}"
    handler = _write_handler(workspace)
    loop: subprocess.Popen | None = None
    started = time.monotonic()

    try:
        created = _run(["mycelium", "room", "create", room], timeout=90)
        if created.returncode != 0:
            return Rung(
                "participate",
                "fail",
                f"room create failed: {(created.stderr or '').strip()[:200]}",
            )

        agent = _run(
            [
                "mycelium",
                "agent",
                "create",
                handle,
                "--adapter",
                spec.family,
                "--room",
                room,
                "--cwd",
                str(workspace),
                "--description",
                "ephemeral harness-conformance probe",
            ],
            timeout=120,
        )
        if agent.returncode != 0:
            return Rung(
                "participate",
                "fail",
                f"agent create failed: {(agent.stderr or '').strip()[:200]}",
            )

        loop = subprocess.Popen(  # noqa: S603 - fixed argv
            [
                "mycelium",
                "await",
                "--loop",
                "--room",
                room,
                "--handle",
                handle,
                "--exec",
                f"{sys.executable} {handler}",
            ],
            env={**os.environ, "HARNESS_ARGV": json.dumps(list(spec.headless_argv))},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=workspace,
        )
        # Wait for the loop's own "awaiting" banner rather than guessing at a
        # sleep: the handle's delivery cursor anchors on that first long-poll, and
        # a mention posted before it lands behind the anchor and is never served.
        if not _await_banner(loop):
            out = (loop.stdout.read() if loop.stdout else "").strip()
            return Rung(
                "participate",
                "fail",
                f"await --loop never reached its first poll: {out[-300:]}",
            )

        mention = _run(
            [
                "mycelium",
                "room",
                "send",
                f"@{handle} Reply with exactly this token and nothing else: {nonce}",
                "--room",
                room,
                "--handle",
                "conformance-driver",
            ],
            timeout=90,
        )
        if mention.returncode != 0:
            return Rung(
                "participate",
                "fail",
                f"room send failed: {(mention.stderr or '').strip()[:200]}",
            )

        deadline = time.monotonic() + PARTICIPATE_TIMEOUT_S
        while time.monotonic() < deadline:
            if _reply_landed(room, handle, nonce):
                elapsed = time.monotonic() - started
                return Rung(
                    "participate",
                    "pass",
                    f"resident loop answered in {elapsed:.1f}s",
                    elapsed,
                )
            if loop.poll() is not None:
                out = (loop.stdout.read() if loop.stdout else "").strip()
                return Rung(
                    "participate",
                    "fail",
                    f"await --loop exited {loop.returncode}: {out[-300:]}",
                )
            time.sleep(5)

        return Rung(
            "participate",
            "fail",
            f"no reply carrying the nonce within {PARTICIPATE_TIMEOUT_S}s",
            time.monotonic() - started,
        )
    finally:
        if loop is not None and loop.poll() is None:
            loop.terminate()
            try:
                loop.wait(timeout=15)
            except subprocess.TimeoutExpired:
                loop.kill()
        # Best-effort teardown: a probe must not leave rooms behind, but a
        # cleanup failure must not turn a real result into a crash.
        for argv in (
            ["mycelium", "agent", "rm", handle, "--room", room, "--force"],
            ["mycelium", "room", "delete", room, "--force"],
        ):
            try:
                _run(argv, timeout=90)
            except (subprocess.TimeoutExpired, OSError):
                pass


# ── driver ───────────────────────────────────────────────────────────────────


def grade(spec: HarnessSpec, *, max_level: str, workspace: Path) -> Report:
    cap = LEVELS.index(max_level)
    rungs: list[Rung] = []
    by_level: dict[str, Rung] = {}

    for index, level in enumerate(LEVELS):
        if index > cap:
            rungs.append(Rung(level, "skip", f"above --max-level={max_level}"))
            continue
        blocker = next(
            (r for r in rungs if r.level in BLOCKING and r.status != "pass"),
            None,
        )
        if blocker is not None:
            rungs.append(Rung(level, "skip", f"'{blocker.level}' did not pass"))
            continue
        if level == "binary":
            rung = probe_binary(spec)
        elif level == "auth":
            rung = probe_auth(spec)
        elif level == "oneshot":
            rung = probe_oneshot(spec, workspace, auth_detected=by_level["auth"].status == "pass")
        else:
            rung = probe_participate(spec, workspace)
        by_level[level] = rung
        rungs.append(rung)

    return Report(
        family=spec.family,
        label=spec.label,
        binary=spec.binary,
        adapter_status=spec.adapter_status,
        rungs=rungs,
    )


_GLYPH = {"pass": "✓", "fail": "✗", "skip": "–"}


def render_markdown(reports: list[Report]) -> str:
    lines = [
        "# Agent-harness conformance",
        "",
        "| Harness | Adapter | binary | auth | oneshot | participate | Reached |",
        "| --- | --- | :-: | :-: | :-: | :-: | --- |",
    ]
    for report in reports:
        cells = " | ".join(_GLYPH[r.status] for r in report.rungs)
        lines.append(
            f"| {report.label} (`{report.binary}`) | {report.adapter_status} | "
            f"{cells} | **{report.highest_pass}** |"
        )
    lines += ["", "<details><summary>Detail</summary>", ""]
    for report in reports:
        lines.append(f"**{report.label}**")
        lines += [f"- `{r.level}` {_GLYPH[r.status]} {r.detail}" for r in report.rungs]
        lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def render_text(reports: list[Report]) -> str:
    out: list[str] = []
    for report in reports:
        out.append(f"\n{report.label}  ({report.binary}, adapter: {report.adapter_status})")
        for rung in report.rungs:
            out.append(f"  {_GLYPH[rung.status]} {rung.level:<12} {rung.detail}")
        out.append(f"  → reached: {report.highest_pass}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="Grade only this family (repeatable). Default: every family in the spec table.",
    )
    parser.add_argument(
        "--max-level",
        choices=LEVELS,
        default="participate",
        help="Highest rung to attempt. Use 'oneshot' where no hub is running.",
    )
    parser.add_argument("--json-report", type=Path, help="Write the full report as JSON here.")
    parser.add_argument("--markdown-report", type=Path, help="Write a markdown summary here.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any FAIL. Without it a FAIL is reported and the exit stays 0.",
    )
    args = parser.parse_args()

    specs = [s for s in HARNESS_SPECS if not args.family or s.family in args.family]
    if not specs:
        parser.error(f"no such family; known: {', '.join(s.family for s in HARNESS_SPECS)}")

    with tempfile.TemporaryDirectory(prefix="harness-conformance-") as tmp:
        workspace = Path(tmp)
        reports = [grade(spec, max_level=args.max_level, workspace=workspace) for spec in specs]

    print(render_text(reports))

    if args.json_report:
        args.json_report.write_text(
            json.dumps([asdict(r) | {"reached": r.highest_pass} for r in reports], indent=2),
            encoding="utf-8",
        )
    markdown = render_markdown(reports)
    if args.markdown_report:
        args.markdown_report.write_text(markdown, encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")

    return 1 if (args.strict and any(r.failed for r in reports)) else 0


if __name__ == "__main__":
    sys.exit(main())
