# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A single custodial session as its OWN OS process, for the two-process restart test (#666).

The productization must prove ``restore_sessions`` resumes a custodial session across a **real**
process boundary — a genuine backend/session bounce, not a single-process App drop
(whose stale subscription confounded the spike's early runs). This runs one custodial session
using the backend's own :mod:`app.services.custody` code so the test exercises the
shipped path, not a spike copy.

Driven by ``tests/test_custody_two_process_restart.py``: the test process is the
always-draining moderator; this subprocess is the custodial session. SIGKILL between phases
drops its connection and the node forgets its subscription, then the ``restore``
phase revives the session from its on-disk MLS state with no re-invite.

Phases (``--phase``):
  ``create``  subscribe + listen for the moderator's invite, publish once, then
              block alive until SIGKILLed (holding the live session).
  ``restore`` re-open the store, ``restore_sessions``, publish once, exit 0.

File signals under ``--workdir`` coordinate with the moderator: ``listening`` (the session
is awaiting the invite — moderator may now invite), ``sent1``/``sent2`` (published).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_WS = "mycelium"


def _touch(workdir: str, name: str) -> None:
    (Path(workdir) / name).write_text("ok")


async def _create(args: argparse.Namespace) -> int:
    from app.services import custody

    cs = await custody.create_session(args.endpoint, _WS, args.room, args.handle)
    join = asyncio.create_task(custody.join_session(cs))
    # Tell the moderator the session is awaiting its invite (listen task scheduled).
    _touch(args.workdir, "listening")
    await join
    await cs.publish(f"phase1: {args.handle} live over MLS".encode())
    _touch(args.workdir, "sent1")
    # Hold the session alive until the moderator SIGKILLs us (the faithful crash).
    while True:
        await asyncio.sleep(0.5)


async def _restore(args: argparse.Namespace) -> int:
    from app.services import custody

    cs = await custody.restore_session(args.endpoint, _WS, args.room, args.handle)
    if cs is None:
        _touch(args.workdir, "restore_empty")
        return 3
    await cs.publish(f"phase2: {args.handle} restored from persisted MLS state".encode())
    _touch(args.workdir, "sent2")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=("create", "restore"))
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--room", required=True)
    ap.add_argument("--handle", required=True)
    ap.add_argument("--workdir", required=True)
    args = ap.parse_args()
    if args.phase == "create":
        return await _create(args)
    return await _restore(args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
