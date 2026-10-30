# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent asks a person something, and gets the answer as a value.

An ask is a message in a task's thread (or the room's channel, when it's about
no task), addressed to one person, whose payload carries ``ask``. It is one of
three kinds: ``approve`` (a yes or no on something the agent will do),
``choose`` (pick one of its ``options``, or several when ``multiple``) and
``question`` (an open question). The agent can say what it would do:
``recommend`` (``"approve"``, or the option ids it would pick) and, on a
question, ``suggest`` (a draft answer).

Any person in the room may answer, never an agent; the one asked is who it
waits on. The answer is a message from whoever answered back to the agent,
addressed to it so it wakes, whose payload carries ``answer``: the decision,
the choices or the text, plus the question it answers and who it was ``for``,
so an agent that lost the ask's id still knows what was decided. Its text
names the question too. Both are messages the room records like any other, so
the transcript is the record; whether an ask was answered is worked out from
it on read and never stored. ``contracts/approvals.json`` freezes the kinds
and fields, since the CLI and the app each keep a copy.

Agents never send UI: they fill in a kind the hub knows and the app draws it.
An answer is final; a new ask is how to try again.
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
KINDS = ("approve", "choose", "question")
DECISIONS = ("approved", "declined")
#: The optional facts an ask of any kind may carry, in the order the card shows them.
FACTS = ("happens", "why", "undo", "link")
#: ``recommend`` on an approve: the agent would go ahead.
RECOMMEND_APPROVE = "approve"
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
        """The ask with its answer on it, as the card reads it."""
        if self.answer is None:
            return dict(self.ask)
        decided = {k: v for k, v in self.answer.items() if k not in {ASK_KEY, "reason"}}
        # An answer from before free text carried its note as ``reason``.
        if self.answer.get("reason") and not decided.get("text"):
            decided["text"] = self.answer["reason"]
        return {**self.ask, ANSWER_KEY: decided}


def asked(records: list[TranscriptRecord], room: str) -> dict[str, Asked]:
    """Every ask in ``records`` by id, each with the first answer it got.

    An ask is the first record that carries its id. An answer counts only when
    a person sent it, as themselves: the routes check who answers, and so does
    this, since any member can publish a frame on the room's channel.
    """
    found: dict[str, Asked] = {}
    for record in records:
        if (ask := ask_on(record)) is not None:
            found.setdefault(str(ask["id"]), Asked(ask=ask, record=record))
        elif (answer := answer_on(record)) is not None:
            hit = found.get(str(answer["ask"]))
            if hit is None or hit.answer is not None:
                continue
            sender = _norm(record.sender)
            if sender == _norm(answer.get("by")) and may_answer(room, sender, hit.ask):
                hit.answer = answer
    return found


def may_answer(room: str, handle: str, ask: dict[str, Any]) -> bool:
    """Whether ``handle`` may answer ``ask``: the person asked, or any other
    person in the room. Never an agent or an engine, so no agent can approve
    its own work, or another's."""
    if not _is_person(room, handle):
        return False
    return handle == _norm(ask.get("to")) or _is_person_here(room, handle)


def records(room: str) -> list[TranscriptRecord]:
    """The room's transcript, live when its channel is up."""
    from app.services.waiting import _records

    return _records(room)


def _is_person(room: str, handle: str) -> bool:
    return principals.classify_sender(room, handle) not in {"agent", "engine"}


def _is_person_here(room: str, handle: str) -> bool:
    """A person the room knows: a user record, or one of the room's people."""
    from app.services import room_people

    kind = principals.classify_sender(room, handle)
    return kind == "user" or (kind == "unknown" and handle in room_people.handles(room))


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
    options: list[dict[str, Any]] | None = None,
    multiple: bool = False,
    recommend: list[str] | str | None = None,
    suggest: str | None = None,
) -> tuple[dict[str, Any], TranscriptRecord, str | None]:
    """Ask, where the agent is working. Returns the ask, its message and the task.

    The task is the one named, else the one whose thread the agent was last
    asked in, else the one task it holds. An agent last asked in the room's
    channel, or holding no one task, asks in the channel: a yes or no about
    no task belongs in the chat it came up in. ``to`` is the one named, else
    :func:`_who_to_ask`.
    """
    question = question.strip()
    if kind not in KINDS:
        raise Refused(422, f"Unknown kind of ask {kind!r}; known: {', '.join(KINDS)}")
    if not question:
        raise Refused(422, "An ask needs a question")
    shape = _shape(kind, options, multiple=multiple, recommend=recommend, suggest=suggest)
    in_channel = bool(recent_episode) and message_format.is_live_episode(room, recent_episode or "")
    key = (
        task
        or _task_of_episode(room, recent_episode)
        or (None if in_channel else _held_task(room, handle))
    )
    if key:
        episode = tasks.episode_of(room, key)
        if not episode:
            raise Refused(404 if task else 422, f"No task {key!r} with a thread in {room!r}")
        refusal = tasks.thread_write_refusal(room, handle, episode)
        if refusal is not None:
            raise Refused(refusal.status, refusal.detail)
    else:
        episode = message_format.live_episode_urn(room)
    person = _norm(to) if to else _who_to_ask(room, key or "", handle)
    if not person:
        raise Refused(422, "Nobody to ask: name them with --to")
    if person == _norm(handle):
        raise Refused(422, "An ask can't be put to whoever is asking")
    if to and not _is_person_here(room, person):
        raise Refused(422, f"@{person} isn't a person in {room!r}; --to names who answers")
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
    ask |= shape
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


def _shape(
    kind: str,
    options: list[dict[str, Any]] | None,
    *,
    multiple: bool,
    recommend: list[str] | str | None,
    suggest: str | None,
) -> dict[str, Any]:
    """What the kind adds to an ask, checked: options for a choose, what the
    agent recommends, and a draft answer for a question."""
    shape: dict[str, Any] = {}
    if kind == "choose":
        labelled = [
            {
                "label": str(o.get("label") or "").strip(),
                "detail": str(o.get("detail") or "").strip(),
            }
            for o in options or []
        ]
        if len(labelled) < 2 or any(not o["label"] for o in labelled):
            raise Refused(422, "A choose needs two or more options, each with a label")
        shape["options"] = [
            {"id": str(n), "label": o["label"], **({"detail": o["detail"]} if o["detail"] else {})}
            for n, o in enumerate(labelled, 1)
        ]
        if multiple:
            shape["multiple"] = True
        if recommend:
            picks = [recommend] if isinstance(recommend, str) else list(recommend)
            known = {o["id"] for o in shape["options"]}
            if any(p not in known for p in picks):
                raise Refused(422, f"recommend names options by number: {', '.join(sorted(known))}")
            if len(picks) > 1 and not multiple:
                raise Refused(422, "Recommend one option, or ask with multiple")
            shape["recommend"] = list(dict.fromkeys(picks))
    elif options or multiple:
        raise Refused(422, "Only a choose has options")
    if kind == "approve" and recommend:
        if recommend not in (RECOMMEND_APPROVE, [RECOMMEND_APPROVE]):
            raise Refused(422, f"On an approve, recommend is {RECOMMEND_APPROVE!r}")
        shape["recommend"] = RECOMMEND_APPROVE
    if kind == "question" and recommend:
        raise Refused(422, "A question has no recommend; give a draft answer with suggest")
    draft = (suggest or "").strip()
    if draft:
        if kind != "question":
            raise Refused(422, "Only a question takes suggest")
        shape["suggest"] = draft
    return shape


def _answered(
    ask: dict[str, Any], decision: str | None, choices: list[str] | None, text: str | None
) -> dict[str, Any]:
    """The answer's values, checked against what its kind takes."""
    kind = str(ask.get("kind") or "approve")
    got: dict[str, Any] = {}
    if kind == "approve":
        if decision not in DECISIONS:
            raise Refused(422, f"An approve is answered with a decision: {', '.join(DECISIONS)}")
        got["decision"] = decision
    elif decision:
        raise Refused(422, "Only an approve takes a decision")
    if kind == "choose":
        options = {str(o.get("id")): str(o.get("label")) for o in ask.get("options") or []}
        picks = list(dict.fromkeys(str(c) for c in choices or []))
        if not picks or any(p not in options for p in picks):
            raise Refused(422, f"A choose is answered with its options' ids: {', '.join(options)}")
        if len(picks) > 1 and not ask.get("multiple"):
            raise Refused(422, "This ask takes one choice")
        got["choices"] = picks
        got["chosen"] = [options[p] for p in picks]
    elif choices:
        raise Refused(422, "Only a choose takes choices")
    if kind == "question" and not text:
        raise Refused(422, "A question is answered with text")
    if text:
        got["text"] = text
    return got


def says(answer: dict[str, Any]) -> str:
    """The answer as the chat reads it, naming the question it answers."""
    question = str(answer.get("question") or "").strip()
    note = str(answer.get("text") or "").strip()
    quoted = f'"{question}"'
    if answer.get("kind") == "choose":
        chosen = ", ".join(f'"{label}"' for label in answer.get("chosen") or [])
        head = f"Chose {chosen} for {quoted}"
    elif answer.get("kind") == "question":
        return f"Answered {quoted}: {note}"
    else:
        head = f"{'Approved' if answer.get('decision') == 'approved' else 'Declined'} {quoted}"
    return f"{head}\n\nNote: {note}" if note else head


async def answer(
    room: str,
    ask_id: str,
    *,
    by: str,
    decision: str | None = None,
    choices: list[str] | None = None,
    text: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], TranscriptRecord]:
    """Answer an ask as ``by``. Returns the folded ask, the answer and its message.

    Any person in the room may answer, never an agent, and only once: the
    check and the post run under one lock per room, so two answers at once
    can't both land.
    """
    lock = _answering.setdefault(room, asyncio.Lock())
    async with lock:
        hit = asked(records(room), room).get(ask_id)
        if hit is None:
            raise Refused(404, f"No ask {ask_id!r} in {room!r}")
        who = _norm(by)
        if not may_answer(room, who, hit.ask):
            raise Refused(403, f"Only a person in {room!r} can answer an ask, not @{who}")
        if hit.answer is not None:
            raise Refused(409, f"Already answered by @{hit.answer.get('by')}")
        episode = hit.episode or message_format.live_episode_urn(room)
        refusal = tasks.thread_write_refusal(room, who, episode)
        if refusal is not None:
            raise Refused(refusal.status, refusal.detail)
        note = (text or "").strip() or None
        decided: dict[str, Any] = {
            "ask": ask_id,
            "kind": str(hit.ask.get("kind") or "approve"),
            "question": str(hit.ask.get("question") or ""),
            "for": _norm(hit.ask.get("to")),
            "by": who,
            "at": datetime.now(UTC).isoformat(),
            **_answered(hit.ask, decision, choices, note),
        }
        record = await _post(
            room,
            sender=who,
            role="human",
            to=_norm(hit.record.sender),
            episode=episode,
            text=says(decided),
            data={ANSWER_KEY: decided},
            parents=[hit.record.message_id] if hit.record.message_id else None,
        )
        hit.answer = decided
        return hit.folded(), decided, record


def open_for(handle: str, records: list[TranscriptRecord], room: str) -> list[Asked]:
    """The unanswered asks put to ``handle``, newest first."""
    me = _norm(handle)
    return [
        hit
        for hit in reversed(asked(records, room).values())
        if hit.answer is None and _norm(hit.ask.get("to")) == me
    ]


def message_id_of(record: TranscriptRecord) -> str:
    """The id the room's history gives an ask's message."""
    return str(read_id(record))
