"""Interactive driver for the *real* aligner — a thin wrapper, no re-implementation.

Runs the actual ``AlignerEngine.mediate()`` end to end against a real per-session
``PiSession``, using the same in-repo fakes the test suite uses for the coordination
stack (``FakePersister``/``FakeManaged``/``FakeManager``). The only thing swapped is
the agent-reply seam: instead of ``FakeChannel``'s canned auto-reply, an
``InteractiveChannel`` surfaces each ``@handle`` prompt to a file and injects the
human's reply back into the transcript the mediator polls. So every stage the real
engine runs — term-mismatch check + clarifying round, opening-positions snapshot,
issue discovery, the SAO loop, verdict + episode-record write — is exercised as
shipped. Nothing about the negotiation flow is duplicated here; this file is a
wrapper with a run function and the file bridge, and it stays that way as the
engine grows.

Protocol (all under --workdir, default /tmp/aligner-lab):
  * The engine addresses one agent; the driver writes that turn to ``turn.json``.
  * You read ``turn.json``, then write the agent's reply prose to ``reply.txt``.
  * The driver injects it as that agent's transcript reply and the engine continues.
  * On termination the real episode record is copied to ``episode.md`` and a
    ``result.json`` summarizes the verdict.

Positions seed from ``positions.json`` in the workdir ({handle: prose}); if absent,
a default two-agent budget scenario is used. LLM config is read from
``~/.mycelium/.env``. Run from fastapi-backend/:

  PYTHONPATH=. uv run python scripts/aligner_driver.py --workdir /tmp/aligner-lab
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

# The episode record is written through the memory filesystem, which is rooted at
# MYCELIUM_DATA_DIR — set it to the workdir before app.config/settings is imported.
_WORKDIR = Path(os.environ.get("ALIGNER_DRIVER_WORKDIR", "/tmp/aligner-lab"))
_DATA_DIR = _WORKDIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MYCELIUM_DATA_DIR", str(_DATA_DIR))
os.environ.setdefault("MYCELIUM_STUB_EMBEDDINGS", "1")

from app.config import settings  # noqa: E402
from app.services import aligner, l9  # noqa: E402
from app.services.l9_models import Kind  # noqa: E402
from app.services.l9_slim import serialize_content  # noqa: E402
from app.services.persister import record_from  # noqa: E402
from app.services.pi_session import PiSession  # noqa: E402
from tests.fakes import FakeManaged, FakeManager, FakePersister  # noqa: E402

_ROOM = "aligner-lab"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)

_DEFAULT_POSITIONS = {
    "growth": "Allocate 60% of the budget to the tech platform rebuild; growth depends on it. Ship in Q3.",
    "risk": "Tech gets at most 30%; the rest to compliance and reserves. Q4 timeline is safer.",
}


def _load_llm_env() -> dict[str, str]:
    """Read LLM_MODEL/API_KEY/BASE_URL from ~/.mycelium/.env (never printed)."""
    env_path = Path.home() / ".mycelium" / ".env"
    out: dict[str, str] = {}
    if env_path.is_file():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k in {"LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"}:
                out[k] = v.strip()
    for k in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


def _position_record(handle: str, text: str, seq: int) -> Any:
    """A transcript reply record from ``handle`` carrying ``text`` — the shape the
    mediator's ``_is_position`` accepts and ``_slim_turn`` / ``_opening_positions``
    read (an agent-role ``exchange`` reply whose content is the prose)."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        sender=handle,
        sender_role="agent",
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=_TOPIC,
        payload_type="reply",
        payload_data={"action": "position"},
        message_id=f"drv-{seq}",
    )
    return record_from(env, serialize_content(env, extra={"content": text}))


class InteractiveChannel:
    """An ``L9SlimChannel`` stand-in whose agent turns are answered by a human.

    On every ``exchange`` prompt the engine sends, surfaces the addressed agent's
    turn to ``turn.json`` and blocks until ``reply.txt`` appears, then injects the
    reply into the persister's log as that agent's transcript reply — exactly what
    a real agent's SLIM/HTTP reply would land as, which is what ``_slim_turn``
    polls for. The ``commit`` envelope is recorded but never prompts.
    """

    def __init__(self, persister: FakePersister, workdir: Path, timeout_s: float) -> None:
        self._persister = persister
        self._turn_file = workdir / "turn.json"
        self._reply_file = workdir / "reply.txt"
        self._timeout_s = timeout_s
        self.sent: list[tuple[Any, dict[str, Any] | None]] = []
        self._seq = 0

    async def send(self, envelope: Any, *, extra: dict[str, Any] | None = None) -> None:
        self.sent.append((envelope, extra))
        if envelope.header.kind != Kind.exchange:
            return
        data = envelope.payload.data
        prompt = (extra or {}).get("content", "")
        for actor in envelope.header.participants.actors[1:]:
            self._seq += 1
            handle = actor.id
            self._turn_file.write_text(
                json.dumps(
                    {
                        "seq": self._seq,
                        "handle": handle,
                        "round": data.get("round"),
                        "action": data.get("action"),
                        "prompt": prompt,
                    },
                    indent=2,
                )
            )
            print(
                f"\n[driver] === TURN {self._seq} — @{handle} "
                f"(round {data.get('round')}, {data.get('action')}) ===\n"
                f"[driver] aligner asks:\n{prompt}\n"
                f"[driver] >>> write @{handle}'s reply to {self._reply_file} <<<",
                flush=True,
            )
            reply = await self._await_reply(handle)
            self._persister.log.record(
                _position_record(handle, reply, self._seq), delivered_to=set()
            )

    async def _await_reply(self, handle: str) -> str:
        deadline = time.monotonic() + self._timeout_s
        while time.monotonic() < deadline:
            if self._reply_file.exists():
                text = self._reply_file.read_text().strip()
                self._reply_file.unlink(missing_ok=True)
                self._turn_file.unlink(missing_ok=True)
                print(f"[driver] @{handle} replied: {text}", flush=True)
                return text
            await asyncio.sleep(0.5)
        print(f"[driver] @{handle} timed out — treating as silence.", flush=True)
        return ""


async def _drive(args: argparse.Namespace) -> None:
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    for stale in ("turn.json", "reply.txt", "result.json", "episode.md"):
        (work / stale).unlink(missing_ok=True)

    pos_file = work / "positions.json"
    positions = json.loads(pos_file.read_text()) if pos_file.is_file() else dict(_DEFAULT_POSITIONS)
    participants = list(positions)

    llm_env = _load_llm_env()
    if not llm_env.get("LLM_MODEL"):
        raise SystemExit("no LLM_MODEL in ~/.mycelium/.env or environment")

    # Pre-seed each agent's opening position into the transcript, the way agents
    # post positions before the aligner is summoned; _opening_positions reads these.
    persister = FakePersister()
    for i, (handle, prose) in enumerate(positions.items()):
        persister.log.record(
            _position_record(handle, prose, i - len(positions)), delivered_to=set()
        )

    channel = InteractiveChannel(persister, work, args.turn_timeout)
    managed = FakeManaged(room=_ROOM, workspace="mycelium", channel=channel, persister=persister)
    manager = FakeManager(managed, participants)

    session_dir = work / "pi-session"
    session_dir.mkdir(exist_ok=True)

    def llm_session_factory(episode: str) -> Any:
        return PiSession(
            session_path=session_dir / "llm_session.jsonl",
            model=llm_env["LLM_MODEL"],
            api_key=llm_env.get("LLM_API_KEY"),
            base_url=llm_env.get("LLM_BASE_URL"),
            binary="pi",
            timeout_s=180.0,
            openshell=False,
        )

    engine = aligner.AlignerEngine(
        manager,  # type: ignore[arg-type]
        handle="aligner",
        round_timeout_s=args.turn_timeout,
        poll_interval_s=0.5,
        max_steps=args.cap,
        llm_session_factory=llm_session_factory,
    )

    print(f"[driver] model={llm_env['LLM_MODEL']}  participants={participants}", flush=True)
    print("[driver] running the real AlignerEngine.mediate() ...", flush=True)
    verdict = await engine.mediate(_ROOM, engine_handle="aligner")

    # The real episode record the engine just wrote — copy it out and summarize.
    episodes = sorted((_DATA_DIR / "rooms" / _ROOM / "log" / "episodes").glob("*.md"))
    record = episodes[-1].read_text() if episodes else "(no episode record written)"
    (work / "episode.md").write_text(record)
    (work / "result.json").write_text(json.dumps({"verdict": verdict}, indent=2, default=str))
    # The verdict is the commit envelope; convergence is its subkind.
    subkind = (verdict or {}).get("header", {}).get("subkind")
    converged = subkind == "converged"
    print(
        f"\n[driver] === DONE — {'AGREEMENT' if converged else 'no agreement'} ===\n"
        f"[driver] verdict={verdict}\n"
        f"[driver] real episode record -> {work / 'episode.md'}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=str(_WORKDIR))
    ap.add_argument("--cap", type=int, default=30, help="max SAO steps")
    ap.add_argument("--turn-timeout", type=float, default=3600.0, help="seconds to wait per reply")
    args = ap.parse_args()
    # The data dir is fixed at import time (settings reads it once), so a --workdir
    # that disagrees would run the turn bridge in one place and read the episode
    # record from another. Point people at the env var rather than half-honor it.
    if Path(args.workdir).resolve() != _WORKDIR.resolve():
        raise SystemExit(
            f"--workdir {args.workdir} disagrees with the data dir under {_WORKDIR}; "
            f"set ALIGNER_DRIVER_WORKDIR={args.workdir} instead (it must be read "
            "before app.config is imported)."
        )
    if not settings.ALIGNER_TERM_CHECK:
        print("[driver] note: ALIGNER_TERM_CHECK is off — stage 0 will be skipped", flush=True)
    asyncio.run(_drive(args))


if __name__ == "__main__":
    main()
