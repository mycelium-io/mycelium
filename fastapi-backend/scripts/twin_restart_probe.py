# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A single twin as its OWN OS process, for the two-process restart test (#666).

The productization must prove ``restore_sessions`` resumes a twin across a **real**
process boundary — a genuine backend/twin bounce, not a single-process App drop
(whose stale subscription confounded the spike's early runs). This runs one twin
using the backend's own :mod:`app.services.twins` code so the test exercises the
shipped path, not a spike copy.

Driven by ``tests/test_twin_two_process_restart.py``: the test process is the
always-draining moderator; this subprocess is the twin. SIGKILL between phases
drops its connection and the node forgets its subscription, then the ``restore``
phase revives the twin from its on-disk MLS state with no re-invite.

Phases (``--phase``):
  ``create``  subscribe + listen for the moderator's invite, publish once, then
              block alive until SIGKILLed (holding the live twin).
  ``restore`` re-open the store, ``restore_sessions``, publish once, exit 0.

File signals under ``--workdir`` coordinate with the moderator: ``listening`` (twin
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
    from app.services import twins

    twin = await twins.create_twin_app(args.endpoint, _WS, args.room, args.handle)
    join = asyncio.create_task(twins.join_twin(twin))
    # Tell the moderator the twin is awaiting its invite (listen task scheduled).
    _touch(args.workdir, "listening")
    await join
    await twin.publish(f"phase1: {args.handle} live over MLS".encode())
    _touch(args.workdir, "sent1")
    # Hold the twin alive until the moderator SIGKILLs us (the faithful crash).
    while True:
        await asyncio.sleep(0.5)


async def _restore(args: argparse.Namespace) -> int:
    from app.services import twins

    twin = await twins.restore_twin(args.endpoint, _WS, args.room, args.handle)
    if twin is None:
        _touch(args.workdir, "restore_empty")
        return 3
    await twin.publish(f"phase2: {args.handle} restored from persisted MLS state".encode())
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
