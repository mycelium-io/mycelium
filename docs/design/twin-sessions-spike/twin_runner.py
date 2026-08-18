# SPDX-License-Identifier: Apache-2.0
"""A single SLIM twin as its OWN OS process, driven by a file-command protocol.

This is what v1 could not do: a *faithful* restart. v1 simulated a twin restart by
dropping an in-memory App inside one process, which left the crashed App's
subscription registered over the shared connection (the confounder documented in
the v1 README). Here each twin is a real subprocess: SIGKILL drops its connection,
the node forgets its subscription, and a fresh subprocess resumes from the on-disk
MLS state with `restore_sessions(new_conn_id)` -- exactly a backend/twin bounce.

The orchestrator (`spike_v2.py`) drives this process by dropping JSON command files
into `--cmddir` and reading JSON result files back. One command at a time; the
runner blocks on each until done, so the event loop keeps servicing SLIM control
traffic (invites, MLS Commits) between commands.

Commands (JSON on stdin-less file protocol):
  {"op":"create_group","room":R}   moderator: create the MLS GROUP
  {"op":"join"}                    member: listen_for_session (await invite)
  {"op":"invite","handle":H}       moderator: route + invite H into the group
  {"op":"remove","handle":H}       moderator: remove H (advances the MLS epoch)
  {"op":"restore"}                 resume sessions from persisted state; -> n
  {"op":"send","text":T}           publish T to the group
  {"op":"recv","timeout":S}        get one message (-> payload+sender or timeout)
  {"op":"quit"}                    exit 0
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path

import slim_bindings

import twin_common as tc


def _atomic_write(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.rename(path)


def _epoch(session) -> int | None:
    for attr in ("epoch", "mls_epoch", "current_epoch"):
        val = getattr(session, attr, None)
        if isinstance(val, int):
            return val
    return None


class Runner:
    def __init__(self, args) -> None:
        self.args = args
        self.conn: int | None = None
        self.app = None
        self.session = None

    async def start(self) -> None:
        slim_bindings.initialize_with_defaults()
        svc = slim_bindings.get_global_service()
        self.conn = await svc.connect_async(
            slim_bindings.new_insecure_client_config(self.args.endpoint)
        )
        wrong = self.args.wrong_passphrase
        self.app, self.name = await tc.make_twin_app(
            svc,
            self.conn,
            self.args.keydir,
            self.args.store,
            self.args.handle,
            passphrase=("WRONG-" + tc.store_passphrase(self.args.handle)) if wrong else None,
        )
        _atomic_write(Path(self.args.cmddir) / "ready.json", {"handle": self.args.handle, "conn": self.conn})

    async def _exec(self, cmd: dict) -> dict:  # noqa: PLR0911, PLR0912 -- flat dispatch
        op = cmd["op"]
        try:
            if op == "create_group":
                room = slim_bindings.Name(tc.ORG, tc.NS, cmd["room"])
                created = self.app.create_session(tc.group_session_config(), room)
                await created.completion.wait_async()
                self.session = created.session
                return {"ok": True, "epoch": _epoch(self.session)}
            if op == "join":
                self.session = await self.app.listen_for_session_async(None)
                return {"ok": True, "epoch": _epoch(self.session)}
            if op == "invite":
                target = slim_bindings.Name(tc.ORG, tc.NS, cmd["handle"])
                await self.app.set_route_async(target, self.conn)
                handle = await self.session.invite_async(target)
                await handle.wait_async()
                return {"ok": True, "epoch": _epoch(self.session)}
            if op == "remove":
                target = slim_bindings.Name(tc.ORG, tc.NS, cmd["handle"])
                handle = await self.session.remove_async(target)
                await handle.wait_async()
                return {"ok": True, "epoch": _epoch(self.session)}
            if op == "restore":
                sessions = await self.app.restore_sessions_async(self.conn)
                self.session = sessions[0] if sessions else None
                return {"ok": True, "n_sessions": len(sessions), "epoch": _epoch(self.session)}
            if op == "send":
                if self.session is None:
                    return {"ok": False, "error": "no session"}
                await self.session.publish_async(cmd["text"].encode(), None, None)
                return {"ok": True}
            if op == "recv":
                if self.session is None:
                    return {"ok": False, "error": "no session"}
                timeout = datetime.timedelta(seconds=cmd.get("timeout", 10))
                msg = await self.session.get_message_async(timeout=timeout)
                return {"ok": True, "payload": msg.payload.decode(errors="replace"),
                        "sender": tc.sender_leaf(msg.context)}
            if op == "quit":
                return {"ok": True, "quit": True}
        except Exception as exc:  # noqa: BLE001 -- spike: report the exact failure
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": False, "error": f"unknown op {op!r}"}

    async def loop(self) -> int:
        cmddir = Path(self.args.cmddir)
        seq = 1
        while True:
            cmd_path = cmddir / f"cmd-{seq}.json"
            if not cmd_path.exists():
                await asyncio.sleep(0.03)
                continue
            cmd = json.loads(cmd_path.read_text())
            res = await self._exec(cmd)
            _atomic_write(cmddir / f"res-{seq}.json", res)
            if cmd["op"] == "quit":
                return 0
            seq += 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--keydir", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--cmddir", required=True)
    ap.add_argument("--wrong-passphrase", action="store_true")
    args = ap.parse_args()
    Path(args.cmddir).mkdir(parents=True, exist_ok=True)
    runner = Runner(args)
    try:
        await runner.start()
    except Exception as exc:  # noqa: BLE001
        _atomic_write(Path(args.cmddir) / "ready.json", {"handle": args.handle, "error": f"{type(exc).__name__}: {exc}"})
        return 2
    return await runner.loop()


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)  # so `import twin_common` resolves
    raise SystemExit(asyncio.run(main()))
