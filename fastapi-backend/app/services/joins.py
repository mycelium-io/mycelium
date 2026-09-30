# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Join codes: how an agent the hub can't reach learns who it is.

Whoever starts an agent (the runner, on its owner's behalf) asks the hub for a
code naming the room and the member. The code travels to the agent in its first
message; the agent runs ``mycelium join <code>``, which trades it here for the
room, the handle and, on a hub with its auth gate on, a token of its own
(``member_tokens``). Nothing about the machine the agent runs on has to be set up
first.

A code is short, single-use, and good for ten minutes, so seeing one in a
transcript is harmless once it has been used. Codes are kept in memory, like
runners; a restart forgets the ones nobody redeemed. Only a hash of each code is
held, so this table can't be read back into working codes.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

#: How long a code can wait to be redeemed.
CODE_TTL_S = 10 * 60
#: Unambiguous letters: no 0/O, 1/I/L.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_GROUPS, _GROUP_LEN = 3, 4


class JoinError(Exception):
    """A code that can't be redeemed: unknown, used, or expired."""


@dataclass(frozen=True)
class Join:
    room: str
    handle: str
    created_by: str | None
    expires_at: float


def _digest(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def normalize(code: str) -> str:
    """A code as typed, however it was spaced or cased: ``ABCD EFGH-ijkl`` -> ``abcd-efgh-ijkl``."""
    letters = "".join(ch for ch in code.lower() if ch.isalnum())
    return "-".join(letters[i : i + _GROUP_LEN] for i in range(0, len(letters), _GROUP_LEN))


class Joins:
    def __init__(self) -> None:
        self._codes: dict[str, Join] = {}
        self._lock = threading.Lock()

    def create(
        self, room: str, handle: str, *, created_by: str | None, now: float | None = None
    ) -> tuple[str, Join]:
        """A new code for ``handle`` in ``room``."""
        now = time.time() if now is None else now
        code = "-".join(
            "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN)) for _ in range(_GROUPS)
        )
        join = Join(room=room, handle=handle, created_by=created_by, expires_at=now + CODE_TTL_S)
        with self._lock:
            self._forget_expired(now)
            self._codes[_digest(code)] = join
        return code, join

    def redeem(self, code: str, *, now: float | None = None) -> Join:
        """The join a code names, used up. Raises :class:`JoinError` if it can't be."""
        now = time.time() if now is None else now
        with self._lock:
            self._forget_expired(now)
            join = self._codes.pop(_digest(code), None)
        if join is None:
            # One answer for unknown, used and expired: which it was would tell a
            # guesser something, and the fix is the same (ask for a new code).
            msg = "that join code isn't valid: it may have been used or expired"
            raise JoinError(msg)
        return join

    def _forget_expired(self, now: float) -> None:
        for key in [k for k, j in self._codes.items() if j.expires_at <= now]:
            del self._codes[key]

    def clear(self) -> None:
        with self._lock:
            self._codes.clear()


joins = Joins()
