# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Machines paired with the desktop app's hub: the one way another machine
connects to it.

The desktop app's hub listens on ``127.0.0.1``. Another machine (a box with
the person's agents on it) reaches it only by pairing:

1. On that machine, ``mycelium runner pair --hub <url>`` prints a code and
   knocks on ``POST /api/pairing/connect`` with a proof that it knows the code
   (an HMAC keyed by it, never the code itself).
2. The person types the code in the app, which hands it to its own hub
   (``POST /api/pairing/expect``, from this computer only). For ten minutes the
   hub waits for a knock carrying a proof made with that code.
3. A knock that proves it gets a token the hub signs, and an entry in this
   computer's ``config.toml``, written here, never by hand::

       [[hub.paired_machines]]
       name = "box"
       id = "…"              # the token names it: pairing again makes a new one
       address = "10.8.0.1"  # the machine's own address: only from here
       listen = "10.8.0.2"   # this computer's address it came in on

From then on the hub also listens on ``listen`` (``machine_listen``), and
answers a request from another machine only when it carries a paired
machine's token (``X-Mycelium-Machine``) from its ``address``
(``machine_gate``). Removing the entry, or ``mycelium runner unpair --hub``
on that machine, shuts it out.

Only a hub that's told where the config file is (``MYCELIUM_PAIRING_CONFIG``,
which the desktop app sets) takes paired machines; any other hub is as before.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import tomllib
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jwt

#: Where the config file paired machines are written to is; unset, no machine pairs.
CONFIG_ENV = "MYCELIUM_PAIRING_CONFIG"
#: The header a paired machine's requests carry its token in. Not
#: ``Authorization``, which says who a request is from: this says which machine.
MACHINE_HEADER = "X-Mycelium-Machine"
#: The ``aud`` of a machine token, so the hub's member tokens are never one.
AUDIENCE = "mycelium-machine"
#: The path a machine knocks on with its proof, the one open while a code waits.
CONNECT_PATH = "/api/pairing/connect"
#: How long a code typed in the app waits for its machine.
WINDOW_S = 10 * 60
#: Wrong proofs a code takes before it's dropped.
MAX_ATTEMPTS = 5
#: How far a knock's time may be from the hub's.
FRESH_S = 5 * 60
#: The code's shape and its key, as the runner makes them (``runner/pairing.py``).
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
OFFER_ID_LEN = 4
CODE_LEN = 12
KDF_ROUNDS = 200_000
NAME_MAX = 40

_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1"})
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_BLOCK = "[[hub.paired_machines]]"
_lock = threading.Lock()


class PairingError(Exception):
    """A request pairing can't take, said for the person."""


@dataclass(frozen=True)
class Machine:
    """One ``[[hub.paired_machines]]`` entry."""

    name: str
    id: str
    #: The machine's own address: its requests come only from here, when set.
    address: str | None = None
    #: This computer's address the machine came in on, which the hub listens on.
    listen: str | None = None


#: The paired machine the request being handled came from, set by the gate;
#: ``None`` for a request from this computer.
_calling: ContextVar[str | None] = ContextVar("paired_machine", default=None)


def calling_machine() -> str | None:
    """The paired machine this request came from, or ``None`` for this computer.

    What a paired machine may do is narrower than what this computer may: it
    queues work only for its own runner (``runners.registry``), and never
    changes this computer's settings (``hub_config``). The app's own runner
    trusts its hub because everything else that reaches it is this computer."""
    return _calling.get()


def enabled() -> bool:
    return bool(os.environ.get(CONFIG_ENV, "").strip())


def config_path() -> Path:
    return Path(os.environ[CONFIG_ENV]).expanduser()


# ── the entries ─────────────────────────────────────────────────────────────


_cache: tuple[float | None, list[Machine]] = (None, [])


def machines() -> list[Machine]:
    """The paired machines in the config file, read again when it changes.
    An entry that isn't whole is left out; a file that doesn't parse pairs none."""
    global _cache
    if not enabled():
        return []
    path = config_path()
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    if mtime is not None and mtime == _cache[0]:
        return _cache[1]
    found: list[Machine] = []
    if mtime is not None:
        try:
            hub = tomllib.loads(path.read_text(encoding="utf-8")).get("hub") or {}
            rows = hub.get("paired_machines") or [] if isinstance(hub, dict) else []
        except (OSError, ValueError, TypeError):
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name, mid = row.get("name"), row.get("id")
            if not isinstance(name, str) or not isinstance(mid, str) or not name or not mid:
                continue
            address, listen = row.get("address"), row.get("listen")
            found.append(
                Machine(
                    name=name,
                    id=mid,
                    address=address if isinstance(address, str) and address else None,
                    listen=listen if isinstance(listen, str) and listen else None,
                )
            )
    _cache = (mtime, found)
    return found


def _block(m: Machine) -> str:
    lines = [_BLOCK, f"name = {json.dumps(m.name)}", f"id = {json.dumps(m.id)}"]
    if m.address:
        lines.append(f"address = {json.dumps(m.address)}")
    if m.listen:
        lines.append(f"listen = {json.dumps(m.listen)}")
    return "\n".join(lines) + "\n"


def _without(text: str, name: str) -> str:
    """``text`` with every ``[[hub.paired_machines]]`` block for ``name`` taken
    out, and everything else in the file left exactly as it was written."""
    out: list[str] = []
    block: list[str] | None = None

    def flush() -> None:
        if block is None:
            return
        try:
            row = tomllib.loads("\n".join(block)).get("hub", {}).get("paired_machines", [{}])[0]
        except (ValueError, IndexError, AttributeError):
            row = {}
        if row.get("name") != name:
            out.extend(block)

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            flush()
            block = [line] if stripped.replace(" ", "") == _BLOCK else None
            if block is not None:
                continue
        if block is not None:
            block.append(line)
        else:
            out.append(line)
    flush()
    return "\n".join(out).rstrip("\n") + "\n" if out else ""


_EMPTY_LIST = re.compile(r"^\s*paired_machines\s*=\s*\[\s*\]\s*(#.*)?$")


def _no_empty_list(text: str) -> str:
    """``text`` without a ``paired_machines = []`` under ``[hub]``, which a
    ``[[hub.paired_machines]]`` table can't follow in valid TOML."""
    out, in_hub = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_hub = stripped.replace(" ", "") == "[hub]"
        elif in_hub and _EMPTY_LIST.match(line):
            continue
        out.append(line)
    return "\n".join(out) + "\n" if out else ""


def _write(text: str) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.pairing")
    tmp.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o600)
    tmp.replace(path)


def add(machine: Machine) -> None:
    """Write ``machine``'s entry, replacing one of the same name."""
    with _lock:
        path = config_path()
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        text = _without(_no_empty_list(text), machine.name)
        sep = "\n" if text and not text.endswith("\n\n") else ""
        _write(f"{text}{sep}{_block(machine)}")


def remove(name: str) -> bool:
    """Take ``name``'s entry out; ``False`` when there wasn't one."""
    with _lock:
        if not any(m.name == name for m in machines()):
            return False
        path = config_path()
        _write(_without(path.read_text(encoding="utf-8"), name))
        return True


# ── codes typed in the app ──────────────────────────────────────────────────


def normalize_code(code: str) -> str:
    clean = re.sub(r"[\s-]", "", code).upper().translate(_LOOKALIKE)
    if len(clean) != CODE_LEN or any(c not in ALPHABET for c in clean):
        raise PairingError(
            "That isn't a pairing code: it's 12 letters and digits, like ABCD-EFGH-JKMN."
        )
    return clean


def derive(code: str) -> bytes:
    """The key a code's proofs are made with, as the runner derives it."""
    salt = f"mycelium-pair:{code[:OFFER_ID_LEN]}".encode()
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt, KDF_ROUNDS, 32)


def connect_message(offer: str, name: str, at: int, nonce: str) -> bytes:
    """What a knock's proof is an HMAC of."""
    return f"mycelium-connect-v1\n{offer}\n{name}\n{at}\n{nonce}".encode()


def _window_path() -> Path:
    from app.services.filesystem import get_data_dir

    return get_data_dir() / "pairing" / "expected.json"


def _expected(now: float | None = None) -> dict[str, dict[str, Any]]:
    now = time.time() if now is None else now
    try:
        found = json.loads(_window_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {
        k: v
        for k, v in found.items()
        if isinstance(v, dict) and isinstance(v.get("until"), (int, float)) and v["until"] > now
    }


def _save_expected(expected: dict[str, dict[str, Any]]) -> None:
    path = _window_path()
    if not expected:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.touch(mode=0o600)
    tmp.write_text(json.dumps(expected))
    tmp.replace(path)


def expect(code: str, *, now: float | None = None) -> tuple[str, float]:
    """Wait for the machine that printed ``code``: its offer id and until when."""
    clean = normalize_code(code)
    now = time.time() if now is None else now
    offer = clean[:OFFER_ID_LEN]
    with _lock:
        expected = _expected(now)
        expected[offer] = {"key": derive(clean).hex(), "until": now + WINDOW_S, "attempts": 0}
        _save_expected(expected)
    return offer, now + WINDOW_S


def window_open(now: float | None = None) -> bool:
    """Whether a code typed in the app is still waiting for its machine (one
    ended by wrong tries isn't, though the hub remembers why it ended)."""
    return enabled() and any(not w.get("dropped") for w in _expected(now).values())


def clean_name(name: str) -> str:
    clean = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")[:NAME_MAX]
    if not clean or not _NAME.match(clean):
        raise PairingError("Give the machine a name: letters, digits and dashes.")
    return clean


def connect(
    *,
    offer: str,
    name: str,
    at: int,
    nonce: str,
    proof: str,
    peer: str,
    local: str,
    now: float | None = None,
) -> tuple[str, Machine]:
    """Pair the machine whose knock proves it knows a code typed in the app:
    its token and its entry, bound to the address it knocked from (``peer``)
    and the one of this computer it reached (``local``). Raises
    :class:`PairingError` otherwise; a wrong proof counts against the code."""
    now = time.time() if now is None else now
    offer = offer.upper()
    with _lock:
        expected = _expected(now)
        waiting = expected.get(offer)
        if waiting is None:
            raise PairingError("No code for this machine is waiting on the hub yet.")
        if waiting.get("dropped"):
            raise PairingError(
                "The code typed on the hub was dropped after too many wrong tries. "
                "Run this again for a new code, and type that one."
            )
        if abs(now - at) > FRESH_S:
            raise PairingError("This machine's clock is too far from the hub's.")
        message = connect_message(offer, name, at, nonce)
        want = hmac.new(bytes.fromhex(waiting["key"]), message, "sha256").digest()
        try:
            got = _unb64url(proof)
        except ValueError:
            got = b""
        if not hmac.compare_digest(want, got):
            waiting["attempts"] = int(waiting.get("attempts", 0)) + 1
            if waiting["attempts"] >= MAX_ATTEMPTS:
                # Remembered until it would have expired, so the next knock
                # says why rather than as though nothing was typed. The key goes.
                expected[offer] = {"dropped": True, "until": waiting["until"]}
            _save_expected(expected)
            raise PairingError("That proof doesn't match the code typed on the hub.")
        expected.pop(offer)
        _save_expected(expected)
    machine = Machine(name=clean_name(name), id=secrets.token_hex(8), address=peer, listen=local)
    add(machine)
    return mint(machine, now=now), machine


def _unb64url(text: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── tokens ──────────────────────────────────────────────────────────────────


def mint(machine: Machine, *, now: float | None = None) -> str:
    """A token for ``machine``, signed with the hub's key. It has no expiry:
    it lasts as long as the entry it names."""
    from app.services import member_tokens

    claims = {
        "iss": member_tokens.ISSUER,
        "aud": AUDIENCE,
        "sub": machine.name,
        "jti": machine.id,
        "iat": int(time.time() if now is None else now),
    }
    return jwt.encode(claims, member_tokens.signing_key(), algorithm=member_tokens.ALGORITHM)


def verify(token: str | None, peer: str | None) -> Machine | None:
    """The paired machine ``token`` is for, when it's signed by this hub, names
    an entry that's still there, and comes from that entry's address."""
    if not token or not enabled():
        return None
    from app.services import member_tokens

    try:
        claims = jwt.decode(
            token,
            member_tokens.verification_key(),
            algorithms=[member_tokens.ALGORITHM],
            audience=AUDIENCE,
            issuer=member_tokens.ISSUER,
            options={"require": ["sub", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    for m in machines():
        if m.id == claims["jti"] and m.name == claims["sub"]:
            return m if m.address is None or m.address == peer else None
    return None


def wire(m: Machine) -> dict[str, Any]:
    return asdict(m)
