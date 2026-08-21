#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "slima2a @ git+https://github.com/agntcy/slim-a2a-python",
#   "slim-bindings==2.1.0",
# ]
# ///
"""Throwaway spike (epic #719): can A2A ride SLIM natively in *our* stack?

Question: AGNTCY ships `slima2a` (agntcy/slim-a2a-python), a SLIMRPC transport
for the a2a-python SDK, so an A2A hop can travel over SLIM instead of plain
HTTPS. Before we decide HTTP-vs-SLIM for the bridge's outbound send, does that
package even coexist with Mycelium's pinned `slim-bindings 2.1.x`, and does it
leave our a2a-sdk usage intact?

This does NOT do a live SLIMRPC round-trip (that needs a running SLIM node +
two endpoints). It answers the dependency + API-surface question, which is the
risk worth retiring first.

Run:  uv run fastapi-backend/spikes/a2a_over_slim_spike.py
"""

from __future__ import annotations

import importlib.metadata as md


def _ver(pkg: str) -> str:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "MISSING"


def main() -> int:
    print("# A2A-over-SLIM dependency spike\n")
    print("[versions resolved together]")
    for pkg in ("slima2a", "slim-bindings", "a2a-sdk"):
        print(f"  {pkg}: {_ver(pkg)}")

    print("\n[slima2a transport API]")
    import slima2a

    print("  exports:", [n for n in dir(slima2a) if not n.startswith("_")])

    print("\n[our bridge's a2a-sdk symbols on this a2a-sdk]")
    from a2a.client import A2ACardResolver, ClientConfig, ClientFactory  # noqa: F401
    from a2a.server.request_handlers import DefaultRequestHandler  # noqa: F401
    from a2a.server.request_handlers.response_helpers import agent_card_to_dict  # noqa: F401
    from a2a.types import Message, SendMessageRequest, StreamResponse  # noqa: F401

    print("  client + server-core + types: all import OK")

    print(
        "\nFindings:\n"
        "  - slima2a coexists with slim-bindings 2.1.0 (its `slim-bindings ~=2.0`).\n"
        "  - BUT slima2a pins `a2a-sdk==1.1.0` exactly; our backend is on 1.1.2.\n"
        "    Adopting the SLIM transport means pinning the whole bridge to\n"
        "    a2a-sdk==1.1.0 (all our symbols exist there — verified above).\n"
        "  - SLIMRPC is point-to-point RPC to a SLIM identity, NOT room-group MLS\n"
        "    membership: it hardens the hop (SLIM identity + encryption vs plain\n"
        "    HTTPS), it does not make the A2A agent a member of the room channel.\n"
        "  - Not proven here: a live SLIMRPC round-trip over a SLIM node."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
