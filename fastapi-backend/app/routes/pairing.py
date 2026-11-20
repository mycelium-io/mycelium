# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/pairing: how another machine connects to the desktop app's hub.

See ``services/paired_machines.py``. ``expect`` and the machine list are this
computer's own (the app, through its own hub), so they answer only a caller on
``127.0.0.1``. ``connect`` is the knock a machine makes with a proof of the
code, the one route another machine reaches without a token (``machine_gate``).
``DELETE /pairing/self`` is a paired machine leaving, with its own token.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import refusals
from app.services import paired_machines
from app.services.machine_gate import is_loopback

router = APIRouter(prefix="/pairing", tags=["pairing"])


class PairingExpect(BaseModel):
    code: str = Field(..., description="The code the machine printed, as typed.")


class PairingExpectRead(BaseModel):
    offer: str = Field(..., description="The code's public first four characters.")
    until: datetime = Field(..., description="When the code stops being waited for.")


class PairingConnect(BaseModel):
    offer: str = Field(..., min_length=4, max_length=4)
    name: str = Field(..., min_length=1, max_length=64, description="The machine's name.")
    at: int = Field(..., description="When the knock was made, in epoch seconds.")
    nonce: str = Field(..., min_length=8, max_length=64)
    proof: str = Field(..., max_length=128, description="HMAC of the knock, keyed by the code.")


class PairedMachineRead(BaseModel):
    name: str
    id: str
    address: str | None = Field(None, description="The machine's address: only from here.")
    listen: str | None = Field(None, description="This computer's address it reaches the hub on.")


class PairingConnectRead(BaseModel):
    token: str = Field(..., description="Sent as X-Mycelium-Machine on every request.")
    machine: PairedMachineRead


def _taken() -> None:
    if not paired_machines.enabled():
        raise HTTPException(
            status_code=404,
            detail="This hub doesn't take paired machines. Only the desktop app's hub does.",
        )


def _from_here(request: Request) -> None:
    if not is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="Only this computer can do that.")


@router.post("/expect", response_model=PairingExpectRead, responses=refusals(403, 404, 422))
async def expect(body: PairingExpect, request: Request) -> PairingExpectRead:
    """Wait ten minutes for the machine that printed ``code`` to knock."""
    _taken()
    _from_here(request)
    try:
        offer, until = await asyncio.to_thread(paired_machines.expect, body.code)
    except paired_machines.PairingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return PairingExpectRead(offer=offer, until=datetime.fromtimestamp(until, tz=UTC))


@router.post("/connect", response_model=PairingConnectRead, responses=refusals(403, 404))
async def connect(body: PairingConnect, request: Request) -> PairingConnectRead:
    """A machine's knock: its token when its proof matches a code typed in the app."""
    _taken()
    peer = request.client.host if request.client else None
    server = request.scope.get("server") or (None,)
    if not peer or is_loopback(peer) or not server[0] or is_loopback(server[0]):
        # A machine is paired by the address it really comes from, which its
        # token is then good from alone. One reaching the hub through a tunnel
        # on this computer arrives as this computer, and its token would be
        # good from anywhere.
        raise HTTPException(
            status_code=403,
            detail="Pair over the other machine's own network address, not a tunnel "
            "on this computer, so the hub knows where it connects from.",
        )
    try:
        token, machine = await asyncio.to_thread(
            paired_machines.connect,
            offer=body.offer,
            name=body.name,
            at=body.at,
            nonce=body.nonce,
            proof=body.proof,
            peer=peer,
            local=server[0],
        )
    except paired_machines.PairingError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    return PairingConnectRead(
        token=token, machine=PairedMachineRead(**paired_machines.wire(machine))
    )


@router.get("/machines", response_model=list[PairedMachineRead], responses=refusals(403, 404))
async def list_machines(request: Request) -> list[PairedMachineRead]:
    """The machines paired with this hub."""
    _taken()
    _from_here(request)
    return [PairedMachineRead(**paired_machines.wire(m)) for m in paired_machines.machines()]


@router.delete("/machines/{name}", status_code=204, responses=refusals(403, 404))
async def unpair_machine(name: str, request: Request) -> None:
    """Shut a paired machine out: its entry goes, and its token with it."""
    _taken()
    _from_here(request)
    if not await asyncio.to_thread(paired_machines.remove, name):
        raise HTTPException(status_code=404, detail=f"No machine named {name!r} is paired.")


@router.delete("/self", status_code=204, responses=refusals(403, 404))
async def leave(request: Request) -> None:
    """A paired machine leaving, with its own token."""
    _taken()
    peer = request.client.host if request.client else None
    token = request.headers.get(paired_machines.MACHINE_HEADER)
    machine = paired_machines.verify(token, peer)
    if machine is None:
        raise HTTPException(status_code=403, detail="This machine isn't paired with this hub.")
    await asyncio.to_thread(paired_machines.remove, machine.name)
