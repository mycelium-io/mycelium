# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Start each agent CLI the way the runner does, and say what happened.

The nightly job (``.github/workflows/nightly.yml``, ``agent-clis``) installs
every CLI in ``integrations.agents.KNOWN`` at its latest release on a clean
machine, one per job, and runs this against it with no key. It goes through
the runner's own host (``HerdrHost.start``: a herdr pane, the CLI's
``launch_args``), so it catches what a person would hit before the model is
ever called: arguments a CLI stopped accepting, a pane whose shell never
reaches its prompt, herdr's first run getting in the way, and a CLI with no
sign-in that the runner can't report as waiting for input.

    uv run python -m mycelium.runner.smoke plan          # the CLIs, as a CI matrix
    uv run python -m mycelium.runner.smoke run codex     # one CLI; exits 1 on a failed check
    uv run python -m mycelium.runner.smoke live claude --api URL --pass ANTHROPIC_API_KEY

``live`` is the paid half (``agent-clis-live``): the CLI signed in, started in
a room on a throwaway hub, mentioned, and expected to answer there without
stopping at a prompt. A run writes its result as JSON (``--out``), which the
job's report reads (``report``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mycelium.integrations.agents import KNOWN, by_id

if TYPE_CHECKING:
    from mycelium.runner.hosts import HerdrHost

#: The room and handle prefix a smoke run starts its agent as.
ROOM = "smoke"
#: How long a started agent is watched before its state is read.
SETTLE_S = 20.0
#: Lines of the pane's screen a result keeps.
SCREEN_LINES = 40
#: What the agent is told if it comes up ready without a sign-in.
INTRO = "This is an automated start-up check. Reply with the single word OK."


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    cli: str
    name: str
    version: str | None = None
    checks: list[Check] = field(default_factory=list)
    #: The pane's screen when the run ended, or when the start failed.
    screen: str | None = None

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:  # noqa: FBT001
        self.checks.append(Check(name, ok, detail))
        return ok


def plan() -> list[dict[str, object]]:
    """Every CLI the app knows, with how to install it, for the job's matrix."""
    return [
        {"cli": k.id, "name": k.name, "install": k.install or "", "herdr": k.herdr_kind is not None}
        for k in KNOWN
    ]


def _version(binary: str) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 - a CLI from the table, by its own name
            [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0][:120] if text else None


def run(cli: str, *, settle_s: float = SETTLE_S) -> Result:
    """Start ``cli`` as the runner would, with no key, and check what it did."""
    from mycelium.runner.daemon import State
    from mycelium.runner.hosts import STEP_SHELL, HerdrHost, HostError

    kind = by_id(cli)
    if kind is None:
        result = Result(cli=cli, name=cli)
        result.check("known", ok=False, detail=f"{cli} isn't in integrations.agents.KNOWN")
        return result
    result = Result(cli=kind.id, name=kind.name)
    binary = next((b for b in kind.binaries if shutil.which(b)), None)
    if not result.check(
        "installed",
        binary is not None,
        f"found {binary}" if binary else f"none of {', '.join(kind.binaries)} is on PATH",
    ):
        return result
    result.version = _version(str(binary))
    if kind.herdr_kind is None:
        result.check(
            "started", ok=True, detail="herdr has no kind for it, so the app doesn't start it"
        )
        return result

    host = HerdrHost()
    if not result.check("herdr", host.available(), "herdr's server answers"):
        return result
    supported = host.kinds()
    if not result.check(
        "herdr knows it",
        supported is None or kind.herdr_kind in supported,
        f"herdr starts it as {kind.herdr_kind}",
    ):
        return result

    state = State()
    handle = f"smoke-{kind.id}"
    pane: str | None = None
    with tempfile.TemporaryDirectory(prefix=f"smoke-{kind.id}-") as cwd:
        env = {"MYCELIUM_AGENT_HANDLE": handle, "MYCELIUM_ROOM_ID": ROOM}
        try:
            started = host.start(
                state,
                room=ROOM,
                handle=handle,
                kind=kind.herdr_kind,
                cwd=Path(cwd),
                env=env,
                intro=INTRO,
            )
        except HostError as e:
            result.screen = e.screen
            if e.step == STEP_SHELL:
                result.check(
                    "shell", ok=False, detail=f"the pane's shell never reached its prompt: {e}"
                )
            else:
                result.check("shell", ok=True)
                result.check("starts", ok=False, detail=f"it didn't come up as an agent: {e}")
            _close(host, e.ref)
            return result
        pane = started.ref
        result.check("shell", ok=True)
        result.check(
            "starts", ok=True, detail=f"accepted {kind.launch_args() or 'no extra arguments'}"
        )
        status = _settle(host, pane, started.status, settle_s)
        result.screen = host.bridge.read_pane(pane, lines=SCREEN_LINES)
        if status is None:
            result.check("stays up", ok=False, detail="it exited after starting")
        elif status == "blocked":
            blocker = host.blocker(pane, kind.herdr_kind) or ""
            result.check(
                "waits for a sign-in",
                ok=True,
                detail="the runner reports it waiting for input, with its screen",
            )
            result.check("says what it waits for", bool(blocker.strip()), blocker[:200])
        else:
            result.check(
                "waits for a sign-in",
                ok=True,
                detail=f"it came up {status} with no key, so there was nothing to sign in to",
            )
        _close(host, pane)
    return result


def _settle(host: HerdrHost, pane: str, first: str | None, settle_s: float) -> str | None:
    """The agent's state once it has had ``settle_s`` to come up; ``None`` if it's gone."""
    deadline = time.monotonic() + settle_s
    status = first
    while time.monotonic() < deadline:
        statuses = host.statuses() or {}
        if pane not in statuses:
            if not host.alive(pane):
                return None
        else:
            status = statuses[pane][0]
            if status == "blocked":
                return status
        time.sleep(2.0)
    return status or "running"


def _close(host: HerdrHost, pane: str | None) -> None:
    if pane:
        try:
            host.bridge.close_pane(pane)
        except Exception:  # noqa: BLE001, S110 - the job's machine is thrown away anyway
            pass


#: Who mentions the agent in a live run.
ASKER = "nightly"
#: How long a live run waits for the agent's answer.
ANSWER_S = 300.0
#: What the agent is told to do once it has read the room, through its notes.
LIVE_NOTES = (
    "This is an automated check that you can take part in a room. Once you have read "
    "the board, run `mycelium await --room {room}` and answer the message it hands you "
    'with `mycelium respond --room {room} --body "..."`. Then stop.'
)


def live(
    cli: str,
    *,
    api: str,
    passthrough: list[str],
    work: str | None = None,
    answer_s: float = ANSWER_S,
) -> Result:
    """Start ``cli`` signed in, in a room on the hub at ``api``, mention it, and
    check it answers there without stopping at a prompt.

    ``passthrough`` names environment variables (its key, its model) handed to
    its pane, and ``work`` is the folder it starts in (one the job trusted for
    it). Signing it in, beyond the key, is the job's business.
    """
    import os
    from contextlib import nullcontext

    import httpx

    from mycelium.runner.daemon import State, intro_prompt
    from mycelium.runner.hosts import HerdrHost, HostError

    kind = by_id(cli)
    result = Result(cli=cli, name=kind.name if kind else cli)
    if kind is None or kind.herdr_kind is None:
        result.check("startable", ok=False, detail=f"the app doesn't start {cli} in herdr")
        return result
    handle = f"live-{kind.id}"
    room = ROOM
    with httpx.Client(base_url=api, timeout=30) as hub:
        hub.post("/api/rooms", json={"name": room}).raise_for_status()
        hub.post("/api/users", json={"handle": ASKER, "display_name": "Nightly"})
        manifest = f"adapter: {kind.adapter}\nframework: {kind.id}\nowner: {ASKER}\n"
        notes = LIVE_NOTES.format(room=room)
        items = [
            {"key": f"agents/{handle}", "value": manifest, "created_by": ASKER, "embed": False},
            {"key": f"agents/{handle}/notes", "value": notes, "created_by": ASKER, "embed": False},
        ]
        hub.post(f"/api/rooms/{room}/memory", json={"items": items}).raise_for_status()

        host = HerdrHost()
        env = {"MYCELIUM_AGENT_HANDLE": handle, "MYCELIUM_ROOM_ID": room, "MYCELIUM_API_URL": api}
        env |= {name: os.environ[name] for name in passthrough if os.environ.get(name)}
        folder = nullcontext(work) if work else tempfile.TemporaryDirectory(prefix="live-")
        with folder as cwd:
            try:
                started = host.start(
                    State(),
                    room=room,
                    handle=handle,
                    kind=kind.herdr_kind,
                    cwd=Path(cwd),
                    env=env,
                    intro=intro_prompt(room, handle, has_notes=True),
                )
            except HostError as e:
                result.screen = e.screen
                result.check("starts", ok=False, detail=str(e))
                return result
            pane = started.ref
            result.check("starts", ok=True)
            if started.status == "blocked":
                result.screen = host.bridge.read_pane(pane, lines=SCREEN_LINES)
                result.check("no prompt", ok=False, detail="it came up stopped at a prompt")
                _close(host, pane)
                return result
            hub.post(
                f"/api/rooms/{room}/messages",
                json={
                    "sender_handle": ASKER,
                    "message_type": "broadcast",
                    "content": f"@{handle} reply with the single word pong",
                },
            ).raise_for_status()
            answered, stopped = _answer(hub, host, room, handle, pane, answer_s)
            result.screen = host.bridge.read_pane(pane, lines=SCREEN_LINES)
            result.check(
                "no prompt",
                not stopped,
                "it stopped at a prompt while working" if stopped else "",
            )
            result.check(
                "answers in the room",
                answered is not None,
                answered or f"no answer from @{handle} within {int(answer_s)}s",
            )
            _close(host, pane)
    return result


def _answer(
    hub: object, host: HerdrHost, room: str, handle: str, pane: str, answer_s: float
) -> tuple[str | None, bool]:
    """``(its answer, whether it stopped at a prompt)``, watching until one happens."""
    deadline = time.monotonic() + answer_s
    while time.monotonic() < deadline:
        resp = hub.get(f"/api/rooms/{room}/messages", params={"limit": 50})  # ty: ignore[unresolved-attribute]
        for message in resp.json().get("messages", []):
            if message.get("sender_handle") == handle and message.get("content"):
                return str(message["content"])[:200], False
        status = (host.statuses() or {}).get(pane, ("", None))[0]
        if status == "blocked":
            return None, True
        time.sleep(5.0)
    return None, False


def markdown(results: list[Result]) -> str:
    """The failed checks, for the nightly issue: which CLI, which check, its screen."""
    failed = [r for r in results if not r.ok]
    if not failed:
        return "Every agent CLI started as the runner starts it."
    parts = []
    for r in failed:
        bad = [c for c in r.checks if not c.ok]
        lines = [f"### {r.name} ({r.version or 'version unknown'})"]
        lines += [f"- **{c.name}**: {c.detail}" for c in bad]
        if r.screen:
            lines += ["", "```", r.screen.rstrip(), "```"]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def main(argv: list[str]) -> int:
    if argv[:1] == ["plan"]:
        print(json.dumps(plan()))  # noqa: T201
        return 0
    if argv[:1] in (["run"], ["live"]) and len(argv) >= 2:
        if argv[0] == "live":
            api = argv[argv.index("--api") + 1] if "--api" in argv else "http://127.0.0.1:8000"
            passed = [argv[i + 1] for i, a in enumerate(argv) if a == "--pass"]
            work = argv[argv.index("--cwd") + 1] if "--cwd" in argv else None
            result = live(argv[1], api=api, passthrough=passed, work=work)
        else:
            result = run(argv[1])
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        payload = json.dumps(asdict(result), indent=2)
        if out:
            Path(out).write_text(payload)
        print(payload)  # noqa: T201
        return 0 if result.ok else 1
    if argv[:1] == ["report"]:
        results = [_load(Path(p)) for p in argv[1:]]
        print(markdown(results))  # noqa: T201
        return 0
    print(__doc__)  # noqa: T201
    return 2


def _load(path: Path) -> Result:
    data = json.loads(path.read_text())
    return Result(
        cli=data["cli"],
        name=data["name"],
        version=data.get("version"),
        checks=[Check(**c) for c in data.get("checks", [])],
        screen=data.get("screen"),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
