# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The A2A bridge send primitive (#714).

``send_to_a2a`` is the client leg: card URL + prompt -> reply prose. The live
wire is exercised by the env-gated test; the hermetic test pins the fail-faithful
contract (a bad endpoint raises rather than fabricating a reply).
"""

import os

import pytest

from app.services.a2a_bridge import A2aSendError, send_to_a2a


@pytest.mark.asyncio
async def test_send_rejects_bad_scheme():
    """A non-http card can't be reached, and that surfaces as A2aSendError."""
    with pytest.raises(A2aSendError):
        await send_to_a2a("ftp://nope", "hi")


@pytest.mark.asyncio
async def test_send_raises_on_unresolvable_card():
    with pytest.raises(A2aSendError, match="unresolvable"):
        await send_to_a2a("https://example.com", "hi")


@pytest.mark.skipif(
    os.getenv("MYCELIUM_A2A_LIVE") != "1",
    reason="live A2A wire test; set MYCELIUM_A2A_LIVE=1 to run",
)
@pytest.mark.asyncio
async def test_send_to_live_public_agent():
    reply = await send_to_a2a("https://hello-world-gxfr.onrender.com", "hello from the seat")
    assert reply.text == "Hello World"
