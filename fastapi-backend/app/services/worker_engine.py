# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The worker engine — a member the hub plays that takes work off the board.

A sixth engine ``kind``, built on the persona's machinery (a Pi session kept
per handle, its ``agents/<handle>/notes`` as character) but a teammate rather
than a character: it answers when a turn is put to it, works a row given to
it, asks another member to review what it did, and resolves what it was asked
to. It is what ``mycelium swarm --server`` fills a room with, so a team can be
seen working on a task with nothing installed but the hub.

**A model in the nodes, code on the edges.** The worker has no tools. What it
decides to *do* to the board it writes as an action line in its reply, and the
engine carries it out through the same services every other writer uses:

- ``[[new: <title> -> @handle]]`` files a child task of the row whose thread it
  is speaking in, given to ``handle``;
- ``[[done]]`` resolves that row.

Action lines are lifted out of the prose before it is posted, the way a stance
marker is.

It hears four things:

- a text **mention** (the summon seam) — a teammate asking it something, most
  often to review;
- an **addressed turn** (``persister.on_addressed``) — how the conductor puts a
  step to one member;
- a row **filed for it** (a ``filed`` notice naming it) — it claims the row and
  works it in the row's thread;
- the last child of a task it split **settling** (a ``resolved`` notice) — it
  writes the combined result into the parent's thread and resolves it.

Unlike a persona, a worker may ``@``-mention a teammate, because asking for a
review is the collaboration; a mention of anything else is neutralized, so a
worker never summons an engine. Turns are serial per worker and capped per
room (:attr:`~app.config.Settings.WORKER_MAX_TURNS_PER_ROOM`), so workers
mentioning each other cannot run forever.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import activity, l9, markers
from app.services.aligner import _norm, _registered_engine_kind
from app.services.l9_models import Kind
from app.services.synthesizer import _strip_fences

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

#: The engine kind this class owns.
ENGINE_KIND = "worker"

#: Where a worker's character lives: the notes memory every agent has.
NOTES_SUFFIX = "/notes"

#: How many recent messages of a thread a turn is shown.
THREAD_CONTEXT = 24

_ACTION = re.compile(r"\[\[\s*(new|done)\b\s*:?\s*([^\]]*)\]\]", re.IGNORECASE)
_NEW_ARGS = re.compile(r"^(?P<title>.+?)\s*(?:->|→)\s*@?(?P<handle>[\w.-]+)\s*$")
_MENTION = re.compile(r"@([\w.-]+)")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

DEFAULT_CHARACTER = (
    "You are a capable, direct member of a small working team. You say what you "
    "think, you do your share, and you check each other's work."
)

WORKER_RULES = """\
You are a member of a team working together in Mycelium, a shared room with a
task board. Each task on the board has its own thread, and you are always
speaking in one of them. You have no tools: your work is what you write, so
when you do a piece of work, write the actual result (the analysis, the plan,
the draft), not a description of what you would do.

You can change the board by putting action lines in your reply, each on its
own line:
  [[new: <short title, in words> -> @<member>]]   file a child task of this thread's task, for that member
  [[done]]                        mark this thread's task done

When the task leaves something open, do not wait for someone to settle it:
say in one line what you will assume, and go on. Nobody may be there to answer.

Writing @name asks that teammate to act: review something, answer a question.
Only do that when you need them to act, never to thank or acknowledge. Talk
like a teammate: short, specific, no filler, no preamble, no code fences."""


@dataclass(frozen=True)
class Action:
    """One thing a reply asked to be done to the board."""

    kind: str
    title: str = ""
    handle: str = ""


_KEY_PREFIX = re.compile(r"^(?:work|decisions|status|failed)/", re.IGNORECASE)


def task_title(raw: str) -> str:
    """A task's title as a person reads it, even when a model wrote it as a key.

    A model asked to file a task sometimes names it the way the board keys it
    (``work/draft-template-structure``); filed as is, the title reads as a path
    and the key doubles its namespace. A key-shaped title is turned back into
    words; anything already in words is kept as written.
    """
    title = raw.strip().strip("\"'`").strip()
    title = _KEY_PREFIX.sub("", title)
    if title and " " not in title and re.search(r"[-_]", title):
        words = re.sub(r"[-_]+", " ", title).strip()
        title = words[:1].upper() + words[1:]
    return title


def parse_actions(text: str) -> tuple[list[Action], str]:
    """``(actions, the prose without them)`` from a worker's reply.

    A ``new`` line that names no member is dropped rather than filed unowned:
    a child task nobody holds is the failure the split exists to prevent.
    """
    actions: list[Action] = []
    for match in _ACTION.finditer(text):
        kind = match.group(1).lower()
        if kind == "done":
            actions.append(Action(kind="done"))
            continue
        args = _NEW_ARGS.match(match.group(2).strip())
        if args:
            title = task_title(args.group("title"))
            if title:
                actions.append(Action(kind="new", title=title, handle=args.group("handle").lower()))
    clean = _ACTION.sub("", text)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return actions, clean


def team_of(room: str) -> list[str]:
    """The room's working members: every agent that is not an engine, plus workers."""
    from app.services.agent_registry import room_agents

    team: list[str] = []
    for agent in room_agents(room):
        if agent.adapter != "engine" or agent.kind == ENGINE_KIND:
            team.append(agent.handle)
    return sorted(team)


def keep_team_mentions(text: str, team: list[str], me: str) -> str:
    """``text`` with every ``@`` that does not name a teammate neutralized.

    A worker asks a teammate to act by naming them, so those mentions stay; a
    mention of anything else (an engine, an unknown handle, itself) loses its
    sigil, so a worker can never summon the aligner or the conductor.
    """
    members = {_norm(h) for h in team} - {_norm(me)}

    def keep(match: re.Match[str]) -> str:
        return match.group(0) if _norm(match.group(1)) in members else match.group(1)

    return _MENTION.sub(keep, text)


def _character(room: str, handle: str) -> str:
    """The worker's own notes, else its description, else the default."""
    import yaml

    from app.services.filesystem import get_room_dir, read_memory_file

    room_dir = get_room_dir(room)
    notes = read_memory_file(room_dir, f"agents/{handle}{NOTES_SUFFIX}")
    if notes is not None and notes[1].strip():
        return notes[1].strip()
    manifest = read_memory_file(room_dir, f"agents/{handle}")
    if manifest is not None:
        try:
            data = yaml.safe_load(manifest[1]) or {}
        except yaml.YAMLError:
            data = {}
        description = data.get("description") if isinstance(data, dict) else None
        if isinstance(description, str) and description.strip():
            return description.strip()
    return DEFAULT_CHARACTER


def _thread_so_far(room: str, episode: str) -> str:
    """The recent conversation in ``episode``, oldest first, one line each."""
    from app.services.persister import prose_messages

    said = [m for m in prose_messages(room) if m.episode == episode and m.content]
    lines = [f"- {m.sender_handle}: {m.content.strip()}" for m in said[-THREAD_CONTEXT:]]
    return "\n".join(lines) or "(nothing yet)"


def _row(room: str, key: str) -> tuple[str, str | None]:
    """``(title, parent key)`` of a board row."""
    from app.services.assignments import PARENT_RELATION
    from app.services.filesystem import get_room_dir, read_memory_file

    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        return key, None
    meta, content = found
    title = next((ln.strip() for ln in content.splitlines() if ln.strip()), key)
    parent = meta.get(PARENT_RELATION)
    return title.lstrip("# ").strip(), parent if isinstance(parent, str) else None


def _parts_of(room: str, parent: str) -> str:
    """Each child of ``parent``: its title and the last thing its holder said in its thread.

    The holder's last message is the version the review settled on, so the
    wrap-up works from the parts themselves rather than from what the lead
    happens to remember of them.
    """
    from app.services.assignments import PARENT_RELATION
    from app.services.filesystem import EPISODE_META, get_room_dir, list_memory_files, system_meta
    from app.services.persister import prose_messages

    said = prose_messages(room)
    blocks: list[str] = []
    for key, meta, content in list_memory_files(get_room_dir(room), prefix="work/"):
        if meta.get(PARENT_RELATION) != parent:
            continue
        title = next((ln.strip() for ln in content.splitlines() if ln.strip()), key)
        author = str(meta.get("owner") or meta.get("assignee") or "").lstrip("@")
        episode = system_meta(meta).get(EPISODE_META)
        final = next(
            (
                m.content.strip()
                for m in reversed(said)
                if m.episode == episode and m.content and _norm(m.sender_handle) == _norm(author)
            ),
            "(nothing posted)",
        )
        blocks.append(f"### {title.lstrip('# ')} (by {author or 'nobody'})\n\n{final}")
    return "\n\n".join(blocks) or "(no parts found)"


def _result_of(room: str, key: str, *, resolver: str, said: str) -> str:
    """The text a row resolves with: what its work produced, not the approval.

    A part is resolved by its reviewer, whose reply is the verdict, so the
    result is the last thing the part's holder said in its thread. A row
    nobody else holds (the parent a lead puts together) resolves with what the
    resolver just said.
    """
    from app.services import tasks
    from app.services.persister import prose_messages

    holder = _holder(room, key)
    if holder is None or _norm(holder) == _norm(resolver):
        return said.strip()
    episode = tasks.episode_of(room, key)
    final = next(
        (
            m.content.strip()
            for m in reversed(prose_messages(room))
            if m.episode == episode and m.content and _norm(m.sender_handle) == _norm(holder)
        ),
        "",
    )
    return final


async def record_result(room: str, key: str, result: str, *, by: str) -> None:
    """Write ``result`` into a resolved row, under its title.

    A task's thread is where the work was argued; the row is what the room
    keeps. Recording the result there makes it a memory like any other,
    indexed and searchable, rather than a message scrolled past. The title
    stays the first line, so the board reads the row as it did; the frontmatter
    (its assignment, its parent, its thread) is carried across by the upsert.
    """
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate
    from app.services.filesystem import get_room_dir, read_memory_file

    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        return
    title = next((ln.strip() for ln in found[1].splitlines() if ln.strip()), key)
    await upsert_memories(
        room,
        MemoryBatchCreate(
            items=[MemoryCreate(key=key, value=f"{title}\n\n{result.strip()}", created_by=by)]
        ),
    )


def _holder(room: str, key: str) -> str | None:
    """Who holds a board row right now, or ``None`` when nobody does."""
    from app.services.assignments import state_of
    from app.services.filesystem import get_room_dir, read_memory_file

    found = read_memory_file(get_room_dir(room), key)
    if found is None or state_of(found[0], datetime.now(UTC)) != "held":
        return None
    return str(found[0].get("owner") or "").lstrip("@") or None


def build_prompt(
    room: str,
    me: str,
    *,
    team: list[str],
    task: tuple[str, str] | None,
    thread: str,
    ask: str,
) -> str:
    """Assemble one turn's prompt. Pure — no I/O, directly unit-testable."""
    others = ", ".join(h for h in team if _norm(h) != _norm(me)) or "nobody else yet"
    where = f"the thread of task {task[0]}: {task[1]}" if task else "the room"
    return (
        f"You are @{me}, in room '{room}', working with {others}.\n"
        f"You are speaking in {where}.\n\n"
        f"The thread so far:\n{thread}\n\n"
        f"{ask}"
    )


def _session_path(room: str, handle: str) -> Path:
    """One session file per (room, handle), so a worker remembers across turns."""
    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    slug = _UNSAFE.sub("-", f"worker-{room}-{handle}").strip("-")
    return session_dir / f"{slug}.jsonl"


def _pi_complete(room: str, handle: str, prompt: str, system: str, timeout_s: float) -> str:
    """One blocking Pi turn on the worker's own persistent session.

    Isolated so tests can patch it without a live Pi.
    """
    from app.services.pi_session import PiSession

    llm_session = PiSession(
        session_path=_session_path(room, handle),
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return llm_session(prompt, system=system)


class WorkerEngine:
    """Take turns, work rows, review each other, and put the result together."""

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        timeout_s: float | None = None,
        max_turns: int | None = None,
    ) -> None:
        self._manager = manager
        self._timeout_s = timeout_s if timeout_s is not None else settings.WORKER_PI_TIMEOUT_S
        self._max_turns = max_turns if max_turns is not None else settings.WORKER_MAX_TURNS_PER_ROOM
        # One turn at a time per worker: a second ask waits its turn rather
        # than being dropped, since a worker is often asked twice in a row (a
        # conductor step, then a row filed for it).
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._turns: dict[str, int] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        #: Parents whose wrap-up has been scheduled, so it happens once.
        self._wrapped: set[tuple[str, str]] = set()

    # -- the seams --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """A teammate mentioned a worker: answer it where it was asked.

        Unless the same text summons a conductor: the handles named beside one
        are its roles, and it addresses each in turn.
        """
        for other in co_summons or ():
            if (
                _norm(other) != _norm(handle)
                and _registered_engine_kind(room, other) == "conductor"
            ):
                return
        self._answer(room, handle, envelope, message_text)

    def handle_addressed(self, room: str, handle: str, envelope: L9, message_text: str) -> None:
        """A turn put to a worker as its L9 recipient: answer it."""
        self._answer(room, handle, envelope, message_text)

    def handle_notice(self, room: str, notice: dict[str, str]) -> None:
        """The board moved: work a row filed for a worker, or wrap up a finished split."""
        subkind = notice.get("subkind")
        if subkind == "filed" and notice.get("for"):
            handle = str(notice["for"]).lstrip("@").lower()
            if not self._is_worker(room, handle):
                return
            key = notice.get("key") or ""
            episode = notice.get("episode") or ""
            if key and episode:
                self._spawn(room, handle, self._work(room, handle, key, episode))
        elif subkind == "resolved" and notice.get("key"):
            from app.services.assignments import parent_completed

            done = parent_completed(room, notice["key"], datetime.now(UTC))
            if done is None:
                return
            parent, lead = done
            # Two parts settling at once both see the split finished; the
            # parent is put back together once.
            if lead and self._is_worker(room, lead) and (room, parent) not in self._wrapped:
                self._wrapped.add((room, parent))
                self._spawn(room, lead, self._wrap_up(room, lead, parent))

    # -- scheduling --

    @staticmethod
    def _is_worker(room: str, handle: str) -> bool:
        return _registered_engine_kind(room, handle) == ENGINE_KIND

    def _answer(self, room: str, handle: str, envelope: L9, message_text: str) -> None:
        if not self._is_worker(room, handle):
            return
        if settings.ENGINE_RUNTIME == "host":
            logger.info("engine @%s summoned in %s but ENGINE_RUNTIME=host", handle, room)
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is None or _norm(sender) == _norm(handle):
            return
        episode = (envelope.header.message.episode if envelope.header.message else None) or ""
        where = episode or l9.live_episode_urn(room)
        ask = (
            f"{sender} said to you:\n\n{message_text.strip()}\n\n"
            f"Answer {sender}. If you were asked to review something, say plainly what "
            "is good and what has to change; when it is good enough, end with [[done]] "
            f"to resolve the task, and if it is not, tell @{sender} exactly what to fix. "
            "If you were asked to fix something, fix it, post the new version, and "
            f"@mention {sender} to look again."
        )
        self._spawn(room, handle, self.turn(room, handle, episode=where, ask=ask))

    def _spawn(self, room: str, handle: str, work: Any) -> None:
        async def serial() -> None:
            lock = self._locks.setdefault((room, _norm(handle)), asyncio.Lock())
            async with lock:
                try:
                    await work
                except Exception:
                    logger.exception("worker @%s failed in room %s", handle, room)

        task = asyncio.create_task(serial())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- the jobs --

    async def _work(self, room: str, handle: str, key: str, episode: str) -> None:
        """Claim a row filed for this worker, then do it in the row's thread."""
        from app.services import assignments

        try:
            await assignments.claim(
                room, key, handle, assignments.DEFAULT_TTL_MINUTES, datetime.now(UTC), force=True
            )
        except assignments.AssignmentError as exc:
            logger.info("worker @%s could not claim %s: %s", handle, key, exc.reason)
            return
        title, _parent = _row(room, key)
        ask = (
            f"The task '{title}' ({key}) is yours. Do it now: write the actual result "
            "in this thread. Then @mention one teammate to review it, saying what to "
            "check. Do not mark it done yourself; the reviewer does."
        )
        await self.turn(room, handle, episode=episode, ask=ask)

    async def _wrap_up(self, room: str, handle: str, parent: str) -> None:
        """Every child of ``parent`` settled: combine them into its thread and resolve it."""
        from app.services import tasks

        episode = tasks.episode_of(room, parent)
        if not episode:
            return
        title, _grand = _row(room, parent)
        ask = (
            f"Every part of '{title}' ({parent}) is done. Here is the final version "
            f"of each part:\n\n{_parts_of(room, parent)}\n\n"
            "Put them together into the one result the task asked for, written out "
            "in full, not summarized. End with [[done]]."
        )
        await self.turn(room, handle, episode=episode, ask=ask)

    # -- the one path: context + ask → one Pi turn → say it, then act --

    async def turn(self, room: str, handle: str, *, episode: str, ask: str) -> str | None:
        """Take one turn as ``handle`` in ``episode``; return what it said.

        ``None`` when the room's turn budget is spent, or the Pi turn fails or
        comes back empty (the reason is posted then, so a silent worker never
        looks like a thinking one).
        """
        from app.services import tasks

        used = self._turns.get(room, 0)
        if used >= self._max_turns:
            logger.info("room %s spent its %d worker turns; @%s stays quiet", room, used, handle)
            return None
        self._turns[room] = used + 1
        managed = self._manager.get(room)
        team = team_of(room)
        row = tasks.row_of_episode(room, episode)
        prompt = build_prompt(
            room,
            handle,
            team=team,
            task=row,
            thread=_thread_so_far(room, episode),
            ask=ask,
        )
        system = f"{WORKER_RULES}\n\n{_character(room, handle)}"
        activity.signal(room, handle, "responding", episode=episode)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, room, handle, prompt, system, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception:
            logger.exception("worker @%s: Pi turn failed in room %s", handle, room)
            await self._say(managed, episode, handle, "Pi turn timed out or errored; ask me again.")
            return None
        finally:
            activity.signal(room, handle, "done", episode=episode)

        reply = _strip_fences(raw or "")
        payload, prose = markers.parse_marker(reply)
        actions, prose = parse_actions(prose)
        prose = keep_team_mentions(prose, team, handle)
        if not prose.strip() and not actions:
            await self._say(
                managed, episode, handle, "Pi returned an empty response; ask me again."
            )
            return None
        if prose.strip():
            await self._say(managed, episode, handle, prose, payload=payload)
            self._manager.enqueue_herdr_wakes_for_mentions(room, prose, exclude=handle)
        await self._act(room, handle, row[0] if row else None, actions, prose)
        if row is not None and prose.strip():
            self._hand_back(room, handle, row[0], episode, prose, actions, team)
        return prose

    def _hand_back(
        self,
        room: str,
        handle: str,
        key: str,
        episode: str,
        prose: str,
        actions: list[Action],
        team: list[str],
    ) -> None:
        """A reply on someone else's row that settles nothing goes back to its holder.

        A review that asks for changes has to reach the member holding the
        row, and a model does not always name them. When a reply here neither
        resolves the row nor mentions a teammate, the holder is the one it was
        for: a worker holder gets the turn, a herdr one its doorbell. Nothing
        is handed back to the one who spoke, so this cannot loop by itself.
        """
        if any(a.kind == "done" for a in actions):
            return
        members = {_norm(h) for h in team} - {_norm(handle)}
        if any(_norm(m) in members for m in _MENTION.findall(prose)):
            return
        holder = _holder(room, key)
        if holder is None or _norm(holder) == _norm(handle) or _norm(holder) not in members:
            return
        if self._is_worker(room, holder):
            ask = (
                f"{handle} said to you:\n\n{prose.strip()}\n\n"
                f"This is about your task {key}. Do what {handle} asked, post the new "
                f"version, and @mention {handle} to look again."
            )
            self._spawn(room, holder, self.turn(room, holder, episode=episode, ask=ask))
        else:
            self._manager.enqueue_herdr_wakes_for_mentions(room, f"@{holder}", exclude=handle)

    @staticmethod
    def _may_resolve(room: str, handle: str, key: str) -> bool:
        """Whether ``handle`` saying ``[[done]]`` on ``key`` resolves it.

        Not when it is already settled: a second reviewer agreeing is not news,
        and every resolve raises a notice the rest of the team reacts to. And
        not a part of a split, by the member holding it, before anyone else
        has said a word in its thread: a part is reviewed before it is done.
        """
        from app.services import tasks
        from app.services.assignments import PARENT_RELATION, settled
        from app.services.filesystem import get_room_dir, read_memory_file
        from app.services.persister import prose_messages

        found = read_memory_file(get_room_dir(room), key)
        if found is None or settled(found[0], datetime.now(UTC)):
            return False
        if found[0].get(PARENT_RELATION) and _norm(_holder(room, key) or "") == _norm(handle):
            episode = tasks.episode_of(room, key)
            others = {_norm(h) for h in team_of(room)} - {_norm(handle)}
            reviewed = any(
                m.episode == episode and _norm(m.sender_handle) in others
                for m in prose_messages(room)
            )
            if not reviewed:
                logger.info("worker @%s marked its own part %s done unreviewed", handle, key)
                return False
        return True

    async def _act(
        self, room: str, handle: str, key: str | None, actions: list[Action], prose: str = ""
    ) -> None:
        """Carry out a reply's action lines against the row its thread belongs to.

        ``prose`` is what the reply said; when it resolves a row nobody holds,
        such as the parent a lead just put together, that is the row's result.
        """
        from app.services import assignments, tasks

        if key is None:
            if actions:
                logger.info("worker @%s acted outside a task's thread; ignoring", handle)
            return
        team = {_norm(h) for h in team_of(room)}
        for action in actions:
            try:
                if action.kind == "new":
                    if _norm(action.handle) not in team:
                        logger.info("worker @%s filed for unknown @%s", handle, action.handle)
                        continue
                    await tasks.create_task(
                        room,
                        action.title,
                        created_by=handle,
                        meta={
                            tasks.ASSIGNEE_FIELD: action.handle,
                            assignments.PARENT_RELATION: key,
                        },
                    )
                elif action.kind == "done" and self._may_resolve(room, handle, key):
                    result = _result_of(room, key, resolver=handle, said=prose)
                    await assignments.resolve(room, key, handle, datetime.now(UTC))
                    if result:
                        await record_result(room, key, result, by=handle)
            except Exception:
                logger.exception("worker @%s could not %s on %s", handle, action.kind, key)

    async def _say(
        self,
        managed: ManagedRoomChannel | None,
        episode: str,
        sender: str,
        text: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Post ``text`` as the worker into ``episode``; off the floor, say nothing."""
        if managed is None:
            logger.warning("worker @%s: no channel for room; dropping reply", sender)
            return
        floor = self._manager.floor(managed.room, episode)
        if floor is not None and not floor.admits(sender):
            logger.info("worker @%s is off the floor in %s; not posting", sender, episode)
            return
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            sender_role="agent",
            topic=l9.topic_urn(managed.room),
            payload_type="reply",
            payload_data=payload or {"action": "reply"},
        )
        try:
            await managed.post(env, text, list_write=True)
        except Exception:
            logger.warning("worker @%s failed to post on room %s", sender, managed.room)
        else:
            await self._manager.raise_ping(
                managed.room,
                episode=episode,
                sender=sender,
                message_id=env.header.message.id if env.header.message else None,
            )
