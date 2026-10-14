# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the doorbell, ``await`` and the wake digest each decide, row by row.

Each row is one message, written the way its sender writes it, and one agent.
Its expected column is what each path decides about that agent: the reason a
wake was queued with (or none), whether ``await`` handed the message over as a
turn, and whether the digest listed it as asking for the agent. A row marked
``wrong`` is one where the paths disagree with each other today.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests import wake_paths
from tests.wake_paths import AGENT, PEER, PERSON, REMOTE, Decided


@dataclass(frozen=True)
class Row:
    id: str
    sender: str
    text: str
    expected: Decided
    to: tuple[str, ...] = ()
    where: str = "room"
    shape: str | None = None
    agent: str = AGENT
    #: Why the paths disagree on this row, when they do.
    wrong: str = ""


ASKED = Decided(doorbell="mention", awaited=True, digest=True)
TURN = Decided(doorbell="turn", awaited=True, digest=True)
NOT_ASKED = Decided(doorbell=None, awaited=False, digest=False)
#: Read as asked by ``await`` and the digest, with no wake rung for it.
UNRUNG = Decided(doorbell=None, awaited=True, digest=True)

ROWS = [
    Row("a person mentions the agent", PERSON, "@coder can you look at the parser?", ASKED),
    Row("a silent mention", PERSON, "thanks @~coder, that was the parser", NOT_ASKED),
    Row(
        "an interrupt",
        PERSON,
        "@!coder stop, that's main",
        Decided(doorbell="interrupt", awaited=True, digest=True),
    ),
    Row("a handle in a code span", PERSON, "run `@coder status` to see it", NOT_ASKED),
    Row("a handle in a code block", PERSON, "like this:\n\n```\n@coder go\n```", NOT_ASKED),
    Row("a mention in another letter case", PERSON, "@Coder can you look?", ASKED),
    Row("an email address", PERSON, "write to coder@example.com", NOT_ASKED),
    Row("a mention of someone else", PERSON, "@planner can you look?", NOT_ASKED),
    Row("an agent mentions itself", AGENT, "@coder note to self: parser next", NOT_ASKED),
    Row(
        "a reply to the agent's turn, not mentioning it",
        PEER,
        "Yes, that command works.",
        UNRUNG,
        to=(AGENT,),
        wrong="respond names whoever it last heard from as recipient, and await counts it",
    ),
    Row(
        "a reply that mentions the agent",
        PEER,
        "@coder can you take the parser?",
        ASKED,
        to=(AGENT,),
    ),
    Row("a reply to someone else", PEER, "Yes, that works.", NOT_ASKED, to=(PERSON,)),
    Row(
        "the aligner puts a turn to the agent",
        "aligner",
        "What's your position on the release date?",
        TURN,
        to=(AGENT,),
        shape="turn",
    ),
    Row(
        "the conductor puts a step to the agent in a thread",
        "conductor",
        "Approve or block this change.",
        TURN,
        to=(AGENT,),
        where="thread",
        shape="turn",
    ),
    Row(
        "an engine turn to someone else",
        "conductor",
        "Approve or block this change.",
        NOT_ASKED,
        to=(PEER,),
        shape="turn",
    ),
    Row(
        "an engine turn that mentions the agent",
        "aligner",
        "@coder your position?",
        UNRUNG,
        to=(AGENT,),
        shape="turn",
        wrong="an engine's text mention rings nothing; only the write routes ring mentions",
    ),
    Row("a persona's post, its @ taken off", "sage", "@coder you should look", NOT_ASKED),
    Row("a worker names a teammate", "builder", "@coder can you review this?", ASKED),
    Row(
        "a mention of an engine",
        PERSON,
        "@aligner what's the plan?",
        UNRUNG,
        agent="aligner",
        wrong="an engine is summoned, but await and the digest read it as asked",
    ),
    Row(
        "a summon of the conductor naming the agent",
        PERSON,
        "@conductor gated @coder @planner: ship the parser",
        UNRUNG,
        wrong="the agent is bound to a role, which the conductor asks later; "
        "await and the digest read the summon as asking it now",
    ),
    Row("a ping", PEER, "", NOT_ASKED, shape="ping"),
    Row("a notice", PEER, "", NOT_ASKED, shape="notice"),
    Row("presence", PEER, "", NOT_ASKED, to=(AGENT,), shape="presence"),
    Row("a commit", "aligner", "agreed: ship friday", NOT_ASKED, to=(AGENT,), shape="commit"),
    Row(
        "a person mentions the agent in a thread",
        PERSON,
        "@coder can you look?",
        ASKED,
        where="thread",
    ),
    Row(
        "a reply in a thread, not mentioning the agent",
        PEER,
        "Yes, that command works.",
        UNRUNG,
        to=(AGENT,),
        where="thread",
        wrong="respond names whoever it last heard from as recipient, and await counts it",
    ),
    Row(
        "an A2A agent answers the agent that summoned it",
        REMOTE,
        "Rain on Friday.",
        UNRUNG,
        to=(AGENT,),
        wrong="a reply's recipient: await and the digest count it, the doorbell doesn't",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("row", ROWS, ids=[r.id for r in ROWS])
async def test_each_path_decides(row: Row, client, monkeypatch) -> None:
    room = await wake_paths.open_room(client, monkeypatch)
    wake_paths.mark_read(room, row.agent)
    await wake_paths.say(room, row.sender, row.text, where=row.where, to=row.to, shape=row.shape)
    got = await wake_paths.decided(room, row.agent)
    assert got == row.expected
    # A row the paths agree on says so; one they disagree on says why.
    assert (len(got.asked) == 1) == (not row.wrong)
