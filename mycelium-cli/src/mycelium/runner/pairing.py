# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Devices paired with this runner, so it can start what they ask without a yes here.

A runner asks the person at its machine before it starts anything a hub sent
it (``approvals``), because a hub can't prove who asked. On a machine nobody
sits at, a pairing stands in for that person: a device (a browser, the Mac
app) holds a private key that never leaves it, and a job it signs is started
without asking, within the limits set here when it was paired.

Pairing happens once, at this machine. ``mycelium runner pair`` writes an
**offer** and prints its code; the first four characters are the offer's id,
which the runner tells the hub so a ``pair`` job can find it, and the rest are
never sent anywhere. The device sends its public key with an HMAC over it,
keyed by the whole code (PBKDF2, so a hub that saw the request can't recover
the code in the ten minutes it lives). The runner checks the HMAC and records
the key with the offer's limits. Nothing over the network can add a pairing
without the code, or widen one at all: the limits are this file's.

A signed job carries ``{"key", "body", "sig"}``. ``body`` is the exact JSON
the device signed (ECDSA P-256, SHA-256, ``r||s``): which runner, which kind,
when, a nonce, and the job's fields as the device asked for them. The runner
verifies the signature over those bytes, then checks every field against the
job the hub delivered, so a hub that edits a job turns its signature into a
refusal. A refused signature isn't an error: the job asks here, as unsigned
ones do, and says why.

Everything lives under ``<runner dir>/pairings``: ``pairings.json``,
``offers/<id>.json`` and ``seen.json`` (nonces already used), all 0600.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: The code's alphabet: Crockford's base32, which a person can read back.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: The public part of a code, which the hub sees and routes by.
OFFER_ID_LEN = 4
#: The whole code: the offer id, then the secret.
CODE_LEN = 12
#: How long a code can be redeemed for.
OFFER_TTL = timedelta(minutes=10)
#: Wrong proofs an offer takes before it is burned.
MAX_ATTEMPTS = 5
#: PBKDF2 rounds on the code: slow enough that a hub can't guess it offline.
KDF_ROUNDS = 200_000
#: How old a signature may be.
FRESH = timedelta(minutes=5)
#: How far ahead of this machine's clock a device's may be.
SKEW = timedelta(minutes=1)
#: The longest name a device may give itself.
NAME_MAX = 40
#: How long a pairing lasts unless the person says otherwise.
DEFAULT_DAYS = 90

_OFFER_ID = re.compile(rf"^[{ALPHABET}]{{{OFFER_ID_LEN}}}$")
_HEX = re.compile(r"^[0-9a-f]{8,64}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
#: Crockford's readings of the letters it leaves out.
_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1"})
_lock = threading.Lock()


class PairingError(Exception):
    """A pairing that can't be made, found or removed, said as a sentence."""


class Refused(Exception):  # noqa: N818 - a verdict, not a failure
    """Why a signed job isn't started without asking."""


def _now() -> datetime:
    return datetime.now(UTC)


def folder(base: Path | None = None) -> Path:
    if base is None:
        from mycelium.runner.daemon import runner_dir

        base = runner_dir()
    path = base / "pairings"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _write(path: Path, body: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(body, f, indent=2)
    tmp.replace(path)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    if not _B64URL.match(text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── keys ─────────────────────────────────────────────────────────────────────


def key_id(x: str, y: str) -> str:
    """A device key's id: SHA-256 of its uncompressed point, 16 hex characters."""
    point = b"\x04" + unb64url(x) + unb64url(y)
    return hashlib.sha256(point).hexdigest()[:16]


def fingerprint(kid: str) -> str:
    """A key id as a person compares it: ``3f9a 12c4 b0de 7781``."""
    return " ".join(kid[i : i + 4] for i in range(0, len(kid), 4))


def _public_key(x: str, y: str):  # noqa: ANN202 - cryptography's key type, imported lazily
    from cryptography.hazmat.primitives.asymmetric import ec

    xs, ys = unb64url(x), unb64url(y)
    if len(xs) != 32 or len(ys) != 32:  # noqa: PLR2004 - a P-256 coordinate
        raise ValueError("not a P-256 key")
    numbers = ec.EllipticCurvePublicNumbers(
        int.from_bytes(xs, "big"), int.from_bytes(ys, "big"), ec.SECP256R1()
    )
    return numbers.public_key()


def verify_signature(x: str, y: str, body: bytes, sig: str) -> bool:
    """Whether ``sig`` (ECDSA P-256 ``r||s``, as WebCrypto makes it) signs ``body``."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    try:
        raw = unb64url(sig)
        if len(raw) != 64:  # noqa: PLR2004 - r and s, 32 bytes each
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        _public_key(x, y).verify(der, body, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return True


# ── codes ────────────────────────────────────────────────────────────────────


def normalize_code(code: str) -> str:
    """A code as typed (any case, dashes, spaces, an O for a 0) in its one spelling."""
    clean = re.sub(r"[\s-]", "", code).upper().translate(_LOOKALIKE)
    if len(clean) != CODE_LEN or any(c not in ALPHABET for c in clean):
        raise PairingError(
            "That isn't a pairing code: it's 12 letters and digits, like ABCD-EFGH-JKMN."
        )
    return clean


def show_code(code: str) -> str:
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def derive(code: str) -> bytes:
    """The key a code's proofs are made with. The browser derives the same with WebCrypto."""
    salt = f"mycelium-pair:{code[:OFFER_ID_LEN]}".encode()
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt, KDF_ROUNDS, 32)


def pair_message(offer: str, name: str, x: str, y: str) -> bytes:
    """What a pairing proof is an HMAC of: the offer, and the device's name and key."""
    return f"mycelium-pair-v1\n{offer}\n{name}\n{x}\n{y}".encode()


def proof(code: str, name: str, x: str, y: str) -> str:
    """The proof a device sends with its key (what the app computes in the browser)."""
    clean = normalize_code(code)
    mac = hmac.new(derive(clean), pair_message(clean[:OFFER_ID_LEN], name, x, y), "sha256")
    return b64url(mac.digest())


# ── pairings ─────────────────────────────────────────────────────────────────


@dataclass
class Limits:
    """What a pairing covers. Empty folders or CLIs mean every one the runner allows."""

    folders: list[str] = field(default_factory=list)
    clis: list[str] = field(default_factory=list)
    swarms: bool = False
    #: ISO time it ends; ``None`` never.
    expires_at: str | None = None

    @classmethod
    def make(
        cls,
        *,
        folders: list[Path] | None = None,
        clis: list[str] | None = None,
        swarms: bool = False,
        days: int = DEFAULT_DAYS,
    ) -> Limits:
        return cls(
            folders=[str(p.expanduser().resolve()) for p in folders or []],
            clis=sorted({c.strip().lower() for c in clis or [] if c.strip()}),
            swarms=swarms,
            expires_at=(_now() + timedelta(days=days)).isoformat() if days > 0 else None,
        )


@dataclass
class Pairing:
    name: str
    key: str
    x: str
    y: str
    paired_at: str
    limits: Limits
    #: The offer it was made from, so ``runner pair`` can tell it landed.
    offer: str = ""

    def expired(self, now: datetime | None = None) -> bool:
        ends = self.limits.expires_at
        return ends is not None and datetime.fromisoformat(ends) <= (now or _now())

    def covers_folder(self, path: Path) -> bool:
        if not self.limits.folders:
            return True
        return any(path == Path(f) or Path(f) in path.parents for f in self.limits.folders)

    def covers_cli(self, cli: str | None) -> bool:
        return not self.limits.clis or (cli or "").lower() in self.limits.clis

    def wire(self) -> dict[str, Any]:
        """What the hub is told: enough for the app to say which devices may start agents here."""
        return {
            "name": self.name,
            "key": self.key,
            "paired_at": self.paired_at,
            "expires_at": self.limits.expires_at,
            "folders": self.limits.folders,
            "clis": self.limits.clis,
            "swarms": self.limits.swarms,
        }

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Pairing:
        return cls(
            name=str(raw["name"]),
            key=str(raw["key"]),
            x=str(raw["x"]),
            y=str(raw["y"]),
            paired_at=str(raw["paired_at"]),
            limits=Limits(**raw.get("limits") or {}),
            offer=str(raw.get("offer") or ""),
        )


def _pairings_path(base: Path | None) -> Path:
    return folder(base) / "pairings.json"


def load(*, base: Path | None = None) -> list[Pairing]:
    raw = _read(_pairings_path(base))
    out = []
    for entry in raw if isinstance(raw, list) else []:
        with contextlib.suppress(TypeError, ValueError, KeyError):
            out.append(Pairing.parse(entry))
    return out


def _save(pairings: list[Pairing], base: Path | None) -> None:
    _write(_pairings_path(base), [asdict(p) for p in pairings])


def live(*, base: Path | None = None) -> list[Pairing]:
    now = _now()
    return [p for p in load(base=base) if not p.expired(now)]


def remove(name: str, *, base: Path | None = None) -> Pairing:
    """Unpair the device called ``name`` (or whose key id starts with it)."""
    with _lock:
        pairings = load(base=base)
        wanted = name.strip().lower()
        match = [p for p in pairings if p.name.lower() == wanted] or [
            p for p in pairings if wanted and p.key.startswith(wanted)
        ]
        if not match:
            raise PairingError(f"Nothing is paired as '{name}'. See them: mycelium runner pairings")
        if len(match) > 1:
            raise PairingError(f"'{name}' names more than one pairing; use its key id.")
        _save([p for p in pairings if p is not match[0]], base)
    return match[0]


def _clean_name(name: str) -> str:
    clean = " ".join("".join(c for c in name if c.isprintable()).split())[:NAME_MAX]
    if not clean:
        raise PairingError("A device needs a name to pair, like 'work laptop'.")
    return clean


# ── offers ───────────────────────────────────────────────────────────────────


def _offers(base: Path | None) -> Path:
    path = folder(base) / "offers"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def offer(limits: Limits, *, base: Path | None = None) -> str:
    """Make an offer and return its code; it lives ``OFFER_TTL``."""
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    oid = code[:OFFER_ID_LEN]
    body = {
        "id": oid,
        "key": derive(code).hex(),
        "limits": asdict(limits),
        "expires_at": (_now() + OFFER_TTL).isoformat(),
        "attempts": 0,
    }
    _write(_offers(base) / f"{oid}.json", body)
    return code


def _offer(oid: str, base: Path | None) -> dict[str, Any] | None:
    if not _OFFER_ID.match(oid):
        return None
    path = _offers(base) / f"{oid}.json"
    body = _read(path)
    if not isinstance(body, dict):
        return None
    if datetime.fromisoformat(str(body["expires_at"])) <= _now():
        path.unlink(missing_ok=True)
        return None
    return body


def live_offers(*, base: Path | None = None) -> list[str]:
    """The ids of the offers that can still be redeemed, which the runner tells the hub."""
    out = []
    for path in sorted(_offers(base).glob("*.json")):
        if _offer(path.stem, base) is not None:
            out.append(path.stem)
    return out


def withdraw(code: str, *, base: Path | None = None) -> None:
    (_offers(base) / f"{code[:OFFER_ID_LEN]}.json").unlink(missing_ok=True)


def landed(code: str, *, base: Path | None = None) -> Pairing | None:
    """The pairing made from ``code``'s offer, once a device redeemed it."""
    oid = code[:OFFER_ID_LEN]
    return next((p for p in load(base=base) if p.offer == oid), None)


def redeem(spec: dict[str, Any], *, base: Path | None = None) -> Pairing:
    """Pair the device a ``pair`` job carries, when its proof is right for a live offer."""
    oid = str(spec.get("offer") or "").upper()
    raw_key = spec.get("key")
    key: dict[str, Any] = raw_key if isinstance(raw_key, dict) else {}
    x, y = str(key.get("x") or ""), str(key.get("y") or "")
    name = _clean_name(str(spec.get("name") or ""))
    with _lock:
        body = _offer(oid, base)
        if body is None:
            raise PairingError("No pairing code here matches, or it expired. Make a new one.")
        try:
            kid = key_id(x, y)
            _public_key(x, y)
        except ValueError as e:
            raise PairingError("The device's key isn't one this machine can use.") from e
        expected = hmac.new(bytes.fromhex(body["key"]), pair_message(oid, name, x, y), "sha256")
        if not hmac.compare_digest(b64url(expected.digest()), str(spec.get("proof") or "")):
            body["attempts"] = int(body.get("attempts", 0)) + 1
            path = _offers(base) / f"{oid}.json"
            if body["attempts"] >= MAX_ATTEMPTS:
                path.unlink(missing_ok=True)
                raise PairingError(
                    "That code is wrong, and it was tried too often. Make a new one."
                )
            _write(path, body)
            raise PairingError("That code is wrong. Check it on the machine and try again.")
        pairings = [p for p in load(base=base) if p.key != kid]
        taken = {p.name.lower() for p in pairings}
        unique, n = name, 2
        while unique.lower() in taken:
            unique, n = f"{name} ({n})", n + 1
        made = Pairing(
            name=unique,
            key=kid,
            x=x,
            y=y,
            paired_at=_now().isoformat(),
            limits=Limits(**body["limits"]),
            offer=oid,
        )
        _save([*pairings, made], base)
        (_offers(base) / f"{oid}.json").unlink(missing_ok=True)
    return made


# ── signed jobs ──────────────────────────────────────────────────────────────


def _seen_once(nonce: str, at: datetime, base: Path | None) -> bool:
    """Record ``nonce``; ``False`` when it was already used."""
    path = folder(base) / "seen.json"
    with _lock:
        raw = _read(path)
        seen = raw if isinstance(raw, dict) else {}
        horizon = (_now() - FRESH - SKEW).timestamp()
        seen = {n: t for n, t in seen.items() if isinstance(t, (int, float)) and t >= horizon}
        if nonce in seen:
            return False
        seen[nonce] = at.timestamp()
        _write(path, seen)
    return True


def signed(job: dict[str, Any], *, runner: str, base: Path | None = None) -> tuple[Pairing, dict]:
    """The pairing that signed ``job`` and the fields it signed, or ``Refused`` saying why.

    Checks the signature, the runner and kind it names, its age and its nonce.
    The caller checks the fields against the job, and the pairing's limits,
    since what a folder resolves to is the runner's business.
    """
    envelope = job.get("signature")
    if not isinstance(envelope, dict):
        raise Refused("it isn't signed")
    kid = str(envelope.get("key") or "")
    pairing = next((p for p in load(base=base) if p.key == kid), None) if _HEX.match(kid) else None
    if pairing is None:
        raise Refused("the device that signed it isn't paired with this machine")
    if pairing.expired():
        raise Refused(f"the pairing with '{pairing.name}' expired")
    body = str(envelope.get("body") or "")
    if not verify_signature(pairing.x, pairing.y, body.encode(), str(envelope.get("sig") or "")):
        raise Refused(f"the signature isn't '{pairing.name}''s")
    try:
        said = json.loads(body)
        at = datetime.fromtimestamp(float(said["ts"]), UTC)
        nonce = str(said["nonce"])
    except (ValueError, KeyError, TypeError) as e:
        raise Refused("the signature doesn't say what it signed") from e
    if said.get("v") != 1 or said.get("runner") != runner or said.get("kind") != job.get("kind"):
        raise Refused("it was signed for a different job")
    now = _now()
    if at < now - FRESH or at > now + SKEW:
        raise Refused("the signature is too old (or the device's clock is off)")
    if not _HEX.match(nonce) or not _seen_once(nonce, at, base):
        raise Refused("the signature was already used")
    fields = said.get("job")
    if not isinstance(fields, dict):
        raise Refused("the signature doesn't say what it signed")
    return pairing, fields
