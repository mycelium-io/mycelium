# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Checking a claim against the room's records: the verifier's second step.

Plain code over one room's transcript, nothing else: what was said in it and the
pull-request notices the status watcher raised into it. Two checks, each about a
pull request a claim sentence names (``#123``):

- **An approval claim.** Somebody other than the speaker approved #N earlier in
  this room, in a message or as a GitHub review the watcher reported. If not, the
  claim can't be confirmed (``sure`` is false: the approval may live somewhere the
  room can't see).
- **A claim that treats #N as still open** ("merge #N", "#N still needs review",
  "stacked on #N"). If #N had already merged more than :data:`GRACE` before the
  message, the records say the opposite (``sure`` is true).

Only the room the claim was made in is read. A finding is a candidate for the
third step (the hub's model reading the thread), never shown on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.services import message_format
from app.services.persister import TranscriptRecord, parse_recorded_at

GRACE = timedelta(minutes=2)
PROSE_TYPES = frozenset({"message", "reply"})

_PR = re.compile(r"#(\d{1,6})\b")
_APPROVAL_WORDS = re.compile(
    r"(?i)\b(approved|approve|approves|lgtm|signed off|sign-off|ready to merge|ok to merge|good to merge)\b"
)
_NEGATED = re.compile(
    r"(?i)\b(not|isn't|hasn't|haven't|no|without|until|once|before|pending|waiting (on|for)|needs?|after)\b[^.\n]{0,25}"
    r"(approv|sign|ready to merge)"
)
_OWN_APPROVAL = re.compile(
    r"(?i)(\*\*APPROVE\*\*|\bI approve\b|\bapproved by me\b|^\s*@[\w-]+\s+#\d+[^.\n]{0,40}\bapprov)"
)
_OPEN = [
    re.compile(r"(?i)\bmerge #(\d{1,6})"),
    re.compile(
        r"(?i)#(\d{1,6})[^.\n]{0,60}\b(still needs|needs|just needs?) (a |its )?(merge|merging|review)"
    ),
    re.compile(
        r"(?i)#(\d{1,6})[^.\n]{0,60}\b(is|are|still) (still )?(in review|awaiting review|waiting (on|for) (a |your )?(review|merge)|open|ready to merge)"
    ),
    re.compile(r"(?i)\b(stack(ed)?( one layer)? on|on top of|rebased? on(to)?) #(\d{1,6})"),
]
_SAYS_MERGED = r"(?i)\b(merged|landed)\b[^.\n]{{0,15}}#{n}\b|#{n}\b[^.\n]{{0,25}}\b(is |was |has been |got )?(merged|landed|in main)\b"


@dataclass
class Finding:
    """A claim the records don't back up, before the hub's model has read it."""

    claim: str  # "approval" or "open"
    ref: str  # "#1278"
    sure: bool  # the records say the opposite, rather than nothing was found
    line: str
    quotes: list[str]
    sentence: str
    checked: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Said:
    sender: str
    at: datetime
    text: str
    message_id: str
    episode: str | None


@dataclass
class _Upstream:
    change: str
    number: str
    at: datetime
    record_id: str


def episode_of(record: TranscriptRecord) -> str | None:
    """The episode (thread or room channel) a record was said in."""
    message = ((record.content.get("l9") or {}).get("header") or {}).get("message") or {}
    episode = message.get("episode")
    return episode if isinstance(episode, str) else None


def _payload(record: TranscriptRecord) -> tuple[str | None, dict[str, Any]]:
    payload = (record.content.get("l9") or {}).get("payload") or {}
    return payload.get("type"), payload.get("data") or {}


def _history(
    records: list[TranscriptRecord], before: datetime
) -> tuple[list[_Said], list[_Upstream]]:
    said, upstream = [], []
    for r in records:
        at = parse_recorded_at(r.recorded_at)
        if at is None or at >= before:
            continue
        ptype, data = _payload(r)
        if ptype in PROSE_TYPES:
            said.append(
                _Said(
                    r.sender, at, str(r.content.get("content") or ""), r.message_id, episode_of(r)
                )
            )
        elif ptype == message_format.NOTICE_PAYLOAD_TYPE and data.get("subkind") == "upstream":
            m = _PR.search(str(data.get("ref") or ""))
            if m:
                when = parse_recorded_at(str(data.get("at") or "")) or at
                upstream.append(
                    _Upstream(str(data.get("change") or ""), m.group(1), when, r.message_id)
                )
    return said, upstream


def _approved(
    n: str, speaker: str, thread: str | None, said: list[_Said], upstream: list[_Upstream]
) -> list[dict[str, str]]:
    """Approvals of #n by someone other than ``speaker``.

    A message naming #n counts anywhere in the room. In a task's own thread an
    approval counts without naming the number ("approved, CI passes"), as long as
    it names no other pull request: that is how reviewers approve in a thread.
    """
    found = [
        {
            "what": f"GitHub review of #{n}",
            "found": "approved",
            "id": u.record_id,
            "at": u.at.isoformat(),
        }
        for u in upstream
        if u.number == n and u.change == "approved"
    ]
    in_thread = thread is not None and not thread.endswith((":live", ":knowledge"))
    for s in said:
        if s.sender == speaker:
            continue
        names_n = f"#{n}" in s.text
        same_thread = in_thread and s.episode == thread and not set(_PR.findall(s.text)) - {n}
        if not (names_n or same_thread):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", s.text):
            if (
                (f"#{n}" in sentence or same_thread)
                and _APPROVAL_WORDS.search(sentence)
                and not _NEGATED.search(sentence)
            ):
                found.append(
                    {
                        "what": f"@{s.sender} on #{n}",
                        "found": "approved",
                        "id": s.message_id,
                        "at": s.at.isoformat(),
                    }
                )
                break
    return found


def _merged_at(
    n: str, said: list[_Said], upstream: list[_Upstream]
) -> tuple[datetime, str, str] | None:
    merges = [
        (u.at, u.record_id, "GitHub") for u in upstream if u.number == n and u.change == "merged"
    ]
    says = re.compile(_SAYS_MERGED.format(n=n))
    merges += [(s.at, s.message_id, f"@{s.sender}") for s in said if says.search(s.text)]
    return min(merges) if merges else None


def check(
    sentence: str,
    kinds: frozenset[str],
    *,
    speaker: str,
    at: datetime,
    thread: str | None,
    records: list[TranscriptRecord],
) -> list[Finding]:
    """What the records say about the claims ``sentence`` makes, said by ``speaker``
    at ``at`` in ``thread`` (the episode it was said in)."""
    refs = list(dict.fromkeys(_PR.findall(sentence)))
    if not refs:
        return []
    said, upstream = _history(records, at)
    findings: list[Finding] = []

    open_refs: dict[str, str] = {}
    for pattern in _OPEN:
        for m in pattern.finditer(sentence):
            n = next(g for g in reversed(m.groups()) if g and g.isdigit())
            open_refs.setdefault(n, m.group(0))
    for n, words in open_refs.items():
        if re.search(_SAYS_MERGED.format(n=n), sentence):
            continue
        merged = _merged_at(n, said, upstream)
        if merged and merged[0] < at - GRACE:
            when, record_id, source = merged
            findings.append(
                Finding(
                    claim="open",
                    ref=f"#{n}",
                    sure=True,
                    line=f"#{n} was already merged, at {when:%H:%M}.",
                    quotes=[words],
                    sentence=sentence,
                    checked=[
                        {
                            "what": f"merges of #{n} in this room",
                            "found": f"merged at {when:%H:%M} ({source})",
                            "id": record_id,
                            "at": when.isoformat(),
                        }
                    ],
                )
            )

    approval_claimed = (
        "approval" in kinds or _APPROVAL_WORDS.search(sentence)
    ) and not _NEGATED.search(sentence)
    if approval_claimed and not _OWN_APPROVAL.search(sentence):
        for n in refs:
            if n in open_refs or not _APPROVAL_WORDS.search(sentence):
                continue
            if _approved(n, speaker, thread, said, upstream):
                continue
            words = _APPROVAL_WORDS.search(sentence)
            quotes = [f"#{n}"] + ([words.group(0)] if words else [])
            findings.append(
                Finding(
                    claim="approval",
                    ref=f"#{n}",
                    sure=False,
                    line=f"Can't find an approval for #{n}.",
                    quotes=quotes,
                    sentence=sentence,
                    checked=[{"what": f"approvals of #{n} in this room", "found": "none"}],
                )
            )
    return findings
