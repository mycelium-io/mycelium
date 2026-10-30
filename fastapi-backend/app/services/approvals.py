# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent asks a person to decide something, and gets the answer as a value.

An ask is a message in a task's thread, addressed to the person, whose payload
carries ``ask`` (``{id, kind, to, question, happens?, why?, undo?, link?}``).
The answer is a message from that person back to the agent, addressed to it so
it wakes, whose payload carries ``answer`` (``{ask, decision, reason?, by,
at}``). Both are messages the room records like any other, so the transcript is
the record; whether an ask was answered is worked out from it on read and never
stored. ``contracts/approvals.json`` freezes the kinds and fields, since the CLI
and the app each keep a copy.

Agents never send UI: they fill in a kind the hub knows (``approve`` for now)
and the app draws it. A decision is final; a new ask is how to try again.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services import message_format, principals, tasks
from app.services.agent_registry import norm_handle
from app.services.message_models import Kind
from app.services.message_slim import serialize_content, serialize_envelope
from app.services.persister import read_id, record_episode

if TYPE_CHECKING:
    from app.services.persister import TranscriptRecord

ASK_KEY = "ask"
ANSWER_KEY = "answer"
KINDS = ("approve",)
DECISIONS = ("approved", "declined")
#: The optional facts an ask may carry, in the order the card shows them.
FACTS = ("happens", "why", "undo", "link")
#: The item kind "Waiting on you" lists an open ask under.
WAITING_KIND = "approve"

_answering: dict[str, asyncio.Lock] = {}


class Refused(Exception):
    """An ask or an answer the hub won't make, with the status to answer with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _norm(handle: object) -> str:
    return norm_handle(str(handle or "").partition("#")[0]) or ""


def _data(record: TranscriptRecord) -> dict[str, Any]:
    data = ((record.content.get("l9") or {}).get("payload") or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def ask_on(record: TranscriptRecord) -> dict[str, Any] | None:
    """The ask ``record`` carries, if it is one."""
    ask = _data(record).get(ASK_KEY)
    return ask if isinstance(ask, dict) and ask.get("id") else None


def answer_on(record: TranscriptRecord) -> dict[str, Any] | None:
    """The answer ``record`` carries, if it is one."""
    answer = _data(record).get(ANSWER_KEY)
    return answer if isinstance(answer, dict) and answer.get("ask") else None


@dataclass
class Asked:
    """One ask as the transcript has it: the message, and its answer if any."""

    ask: dict[str, Any]
    record: TranscriptRecord
    answer: dict[str, Any] | None = None

    @property
    def episode(self) -> str | None:
        return record_episode(self.record)

    def folded(self) -> dict[str, Any]:
        """The ask with its decision on it, as the card reads it."""
        if self.answer is None:
            return dict(self.ask)
        decided = {k: self.answer.get(k) for k in ("decision", "reason", "by", "at")}
        return {**self.ask, ANSWER_KEY: decided}


def asked(records: list[TranscriptRecord]) -> dict[str, Asked]:
    """Every ask in ``records`` by id, each with the first answer it got."""
    found: dict[str, Asked] = {}
    for record in records:
        if (ask := ask_on(record)) is not None:
            found.setdefault(str(ask["id"]), Asked(ask=ask, record=record))
        elif (answer := answer_on(record)) is not None:
            hit = found.get(str(answer["ask"]))
            if hit is not None and hit.answer is None:
                hit.answer = answer
    return found


def records(room: str) -> list[TranscriptRecord]:
    """The room's transcript, live when its channel is up."""
    from app.services.waiting import _records

    return _records(room)


def _is_person(room: str, handle: str) -> bool:
    return principals.classify_sender(room, handle) not in {"agent", "engine"}


def _who_to_ask(room: str, key: str, handle: str) -> str | None:
    """Who an ask goes to when the agent names nobody: the person who filed the
    task, else whoever filed the nearest task it is part of, else the asking
    agent's owner."""
    from app.services.board import parent_of
    from app.services.filesystem import get_room_dir, read_memory_file

    room_dir = get_room_dir(room)
    seen: set[str] = set()
    while key and key not in seen:
        seen.add(key)
        found = read_memory_file(room_dir, key)
        if found is None:
            break
        meta = found[0]
        filer = _norm(meta.get("created_by"))
        if filer and filer != _norm(handle) and _is_person(room, filer):
            return filer
        key = parent_of(meta) or ""
    manifest = principals._read_agent_manifest(room, _norm(handle))
    owner = _norm((manifest or {}).get("owner"))
    return owner or None


def _held_task(room: str, handle: str) -> str | None:
    """The one open task ``handle`` holds, if it holds exactly one."""
    from app.services import assignments
    from app.services.board import _Rows
    from app.services.filesystem import EPISODE_META, system_meta

    now = datetime.now(UTC)
    rows = _Rows(room, now)
    me = _norm(handle)
    held = [
        key
        for key, (meta, _content) in rows.rows.items()
        if _norm(assignments.holder(meta, now)) == me
        and not rows.settled(key)
        and system_meta(meta).get(EPISODE_META)
    ]
    return held[0] if len(held) == 1 else None


def _task_of_episode(room: str, episode: str | None) -> str | None:
    if not episode or message_format.is_live_episode(room, episode):
        return None
    row = tasks.row_of_episode(room, episode)
    return row[0] if row else None


async def _post(
    room: str,
    *,
    sender: str,
    role: str,
    to: str,
    episode: str,
    text: str,
    data: dict[str, Any],
    parents: list[str] | None = None,
) -> TranscriptRecord:
    """Record and broadcast one message from ``sender`` addressed to ``to``.

    Addressed rather than mentioned, and not a ``reply``, so it asks ``to``
    by the one rule (``asks.py``): it wakes an agent, and lists under a
    person's Waiting on you.
    """
    from app.services import room_channels

    managed = await room_channels.manager.provision(room)
    if managed is None or managed.persister is None:
        raise Refused(503, "No live channel for room")
    envelope = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        sender_role=role,
        recipients=[to],
        topic=message_format.topic_urn(room),
        payload_type="message",
        payload_data=data,
        parents=parents or [],
    )
    extra = {"content": text}
    before = len(managed.persister.log.records)
    managed.persister.ingest_local(
        envelope, serialize_content(envelope, extra=extra), list_write=True
    )
    if not await room_channels.manager.send_as_custodian(
        room, sender, serialize_envelope(envelope, extra=extra)
    ):
        try:
            await managed.channel.send(envelope, extra=extra)
        except Exception:
            pass
    message_id = envelope.header.message.id if envelope.header.message else None
    await room_channels.manager.raise_ping(
        room, episode=episode, sender=sender, message_id=message_id
    )
    recorded = managed.persister.log.records[before:]
    return next((r for r in recorded if r.message_id == message_id), recorded[-1])


async def create(
    room: str,
    handle: str,
    *,
    question: str,
    kind: str = "approve",
    to: str | None = None,
    task: str | None = None,
    recent_episode: str | None = None,
    facts: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any], TranscriptRecord, str | None]:
    """Ask, in a task's thread. Returns the ask, its message and the task.

    The task is the one named, else the one whose thread the agent was last
    asked in, else the one task it holds. ``to`` is the one named, else
    :func:`_who_to_ask`.
    """
    question = question.strip()
    if kind not in KINDS:
        raise Refused(422, f"Unknown kind of ask {kind!r}; known: {', '.join(KINDS)}")
    if not question:
        raise Refused(422, "An ask needs a question")
    key = task or _task_of_episode(room, recent_episode) or _held_task(room, handle)
    if not key:
        raise Refused(422, "No task to ask in: name it with --task")
    episode = tasks.episode_of(room, key)
    if not episode:
        raise Refused(404 if task else 422, f"No task {key!r} with a thread in {room!r}")
    refusal = tasks.thread_write_refusal(room, handle, episode)
    if refusal is not None:
        raise Refused(refusal.status, refusal.detail)
    person = _norm(to) if to else _who_to_ask(room, key, handle)
    if not person:
        raise Refused(422, "Nobody to ask: name them with --to")
    if person == _norm(handle):
        raise Refused(422, "An ask can't be put to whoever is asking")
    ask: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "to": person,
        "question": question,
    }
    for fact in FACTS:
        value = str((facts or {}).get(fact) or "").strip()
        if value:
            ask[fact] = value
    record = await _post(
        room,
        sender=handle,
        role="agent",
        to=person,
        episode=episode,
        text=question,
        data={ASK_KEY: ask},
    )
    return ask, record, key


async def answer(
    room: str, ask_id: str, *, decision: str, by: str, reason: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], TranscriptRecord]:
    """Answer an ask as ``by``. Returns the folded ask, the answer and its message.

    Only the person asked may answer, and only once: the check and the post run
    under one lock per room, so two answers at once can't both land.
    """
    if decision not in DECISIONS:
        raise Refused(422, f"Unknown decision {decision!r}; known: {', '.join(DECISIONS)}")
    lock = _answering.setdefault(room, asyncio.Lock())
    async with lock:
        hit = asked(records(room)).get(ask_id)
        if hit is None:
            raise Refused(404, f"No ask {ask_id!r} in {room!r}")
        if _norm(by) != _norm(hit.ask.get("to")):
            raise Refused(403, f"This ask is for @{hit.ask.get('to')}, not @{_norm(by)}")
        if hit.answer is not None:
            raise Refused(409, f"Already {hit.answer.get('decision')} by @{hit.answer.get('by')}")
        episode = hit.episode or message_format.live_episode_urn(room)
        refusal = tasks.thread_write_refusal(room, _norm(by), episode)
        if refusal is not None:
            raise Refused(refusal.status, refusal.detail)
        reason = (reason or "").strip() or None
        decided: dict[str, Any] = {
            "ask": ask_id,
            "decision": decision,
            "by": _norm(by),
            "at": datetime.now(UTC).isoformat(),
        }
        if reason:
            decided["reason"] = reason
        text = "Approved." if decision == "approved" else "Declined."
        if reason:
            text = f"{text} {reason}" if decision == "approved" else f"Declined: {reason}"
        record = await _post(
            room,
            sender=_norm(by),
            role="human",
            to=_norm(hit.record.sender),
            episode=episode,
            text=text,
            data={ANSWER_KEY: decided},
            parents=[hit.record.message_id] if hit.record.message_id else None,
        )
        hit.answer = decided
        return hit.folded(), decided, record


def open_for(handle: str, records: list[TranscriptRecord]) -> list[Asked]:
    """The unanswered asks put to ``handle``, newest first."""
    me = _norm(handle)
    return [
        hit
        for hit in reversed(asked(records).values())
        if hit.answer is None and _norm(hit.ask.get("to")) == me
    ]


def message_id_of(record: TranscriptRecord) -> str:
    """The id the room's history gives an ask's message."""
    return str(read_id(record))
