# SPDX-License-Identifier: Apache-2.0
"""Assemble the room-roster JWKS from members' ES256 public-key PEMs (spike #587).

The roster JWKS is the SignerJwt floor's trust surface: the set of public keys a
member's verifier will accept a self-signed token from. In a real mycelium
deployment this is the moderator's view of the room's registered agents -- one JWK
per `mycelium agent credential set`. Here it is just the two spike members.

Usage: python build_roster_jwks.py <keydir> <name> [<name> ...]
Reads <keydir>/<name>.pub.pem for each name, writes <keydir>/roster-jwks.json.
"""

import base64
import json
import sys

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> int:
    keydir, names = sys.argv[1], sys.argv[2:]
    keys = []
    for name in names:
        with open(f"{keydir}/{name}.pub.pem", "rb") as fh:
            pub = load_pem_public_key(fh.read())
        if not isinstance(pub, ec.EllipticCurvePublicKey):
            raise TypeError(f"{name}: expected an EC P-256 public key")
        nums = pub.public_numbers()
        keys.append(
            {
                "kty": "EC",
                "crv": "P-256",
                "alg": "ES256",
                "use": "sig",
                "kid": name,  # the @handle; lets the verifier do O(1) key lookup
                "x": _b64u(nums.x.to_bytes(32, "big")),
                "y": _b64u(nums.y.to_bytes(32, "big")),
            }
        )
    out = f"{keydir}/roster-jwks.json"
    with open(out, "w") as fh:
        json.dump({"keys": keys}, fh)
    print(f"wrote {out} with {len(keys)} key(s): {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
