# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Checking a claim against the room's records: the verifier's second step.

Plain code over one room's transcript, nothing else: what was said in it and the
pull-request notices the status watcher raised into it. Two checks, each about a
pull request a claim sentence names:

- **An approval claim.** Somebody other than the speaker approved it earlier in
  this room, in a message or as a GitHub review the watcher reported. If not, the
  claim can't be confirmed (``sure`` is false: the approval may live somewhere the
  room can't see).
- **A claim that treats it as still open** ("merge #N", "#N still needs review",
  "stacked on #N"). If it had already merged more than :data:`GRACE` before the
  message, the records say the opposite (``sure`` is true).

A pull request is a repository and a number, because a room talks about more
than one repository and their numbers overlap. A reference names its repository
when it is written ``repo#N``, ``owner/repo#N`` or as a pull request's URL, and
the watcher's notices always do. A bare ``#N`` takes the repository its sentence
names, if it names one (a repository the room has mentioned, as a word); a
sentence naming two leaves it unknown, and an unknown reference is never checked.
Evidence has to be about the same pull request. For an approval that is lenient,
since a missing approval is shown as "can't find": a bare ``#N`` matches any
repository's. For a merge it is strict, since a merge line is shown as certain: a
bare ``#N`` matches a named repository's only when that repository is the only
one the watcher has reported a ``#N`` for.

Talk about a merge that hasn't happened ("once #N is merged", "#N isn't merged
yet") is not a merge.

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

#: A pull request: its repository (lowercase name, ``None`` when unsaid, ``"?"``
#: when the sentence names more than one) and its number.
Ref = tuple[str | None, str]
UNKNOWN = "?"

#: One reference as written: a pull request's URL, ``[owner/]repo#N``, or ``#N``.
_REF = (
    r"(?:https?://github\.com/[\w.-]+/[\w.-]+/pull/\d{1,6}"
    r"|(?:[\w.-]+/)?[A-Za-z][\w.-]*#\d{1,6}"
    r"|(?<![\w.-])#\d{1,6})"
)
_REF_RE = re.compile(_REF)
_URL = re.compile(r"github\.com/[\w.-]+/([\w.-]+)/pull/(\d{1,6})")
_QUALIFIED = re.compile(r"(?:[\w.-]+/)?([A-Za-z][\w.-]*)#(\d{1,6})")
_BARE = re.compile(r"#(\d{1,6})")
#: Words written straight before a ``#`` that name no repository ("PR#12").
_NOT_REPOS = frozenset({"pr", "prs", "pull", "issue", "issues", "mr"})
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")

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
    re.compile(rf"(?i)\bmerge (?P<ref>{_REF})"),
    re.compile(
        rf"(?i)(?P<ref>{_REF})[^.\n]{{0,60}}\b(still needs|needs|just needs?) (a |its )?(merge|merging|review)"
    ),
    re.compile(
        rf"(?i)(?P<ref>{_REF})[^.\n]{{0,60}}\b(is|are|still) (still )?(in review|awaiting review|waiting (on|for) (a |your )?(review|merge)|open|ready to merge)"
    ),
    re.compile(rf"(?i)\b(stack(ed)?( one layer)? on|on top of|rebased? on(to)?) (?P<ref>{_REF})"),
]
_MERGED = [
    re.compile(rf"(?i)\b(merged|landed)\b[^.\n#]{{0,15}}(?P<ref>{_REF})"),
    re.compile(
        rf"(?i)(?P<ref>{_REF})[^.\n#]{{0,25}}\b(is |was |has been |got )?(merged|landed|in main)\b"
    ),
]
#: A sentence about a merge that hasn't happened, or might not.
_MERGE_NOT_YET = re.compile(
    r"(?i)\b(once|after|until|when|whenever|before|if|unless|not|isn't|hasn't|wasn't|aren't|haven't|yet|pending|waiting|will|should|needs?)\b"
)


@dataclass
class Finding:
    """A claim the records don't back up, before the hub's model has read it."""

    claim: str  # "approval" or "open"
    ref: str  # "#1278", or "mycelium-classifier#3" when the repository was named
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
    ref: Ref
    at: datetime
    record_id: str


@dataclass
class _Records:
    """What the room said and was told before the claim, and how to read its refs."""

    said: list[_Said]
    upstream: list[_Upstream]
    known: frozenset[str]  # repositories the room has named
    reported: dict[str, set[str]]  # a number -> the repositories the watcher reported it for


def label(ref: Ref) -> str:
    repo, n = ref
    return f"{repo}#{n}" if repo and repo != UNKNOWN else f"#{n}"


def _parse(token: str) -> Ref:
    m = _URL.search(token)
    if m:
        return m.group(1).lower(), m.group(2)
    m = _QUALIFIED.fullmatch(token)
    if m and m.group(1).lower() not in _NOT_REPOS:
        return m.group(1).lower(), m.group(2)
    m = _BARE.search(token)
    return None, m.group(1) if m else ""


def _named(sentence: str, known: frozenset[str]) -> set[str]:
    """The repositories ``sentence`` names, in a reference or as a word."""
    named = {r for r, _ in (_parse(t) for t in _REF_RE.findall(sentence)) if r}
    named |= {r for r in known if re.search(rf"(?i)(?<![\w.-]){re.escape(r)}(?![\w.-])", sentence)}
    return named


def _resolve(tokens: list[str], sentence: str, known: frozenset[str]) -> list[tuple[Ref, str]]:
    """Each written reference as a pull request, with the words it was written in."""
    named = _named(sentence, known)
    out: dict[Ref, str] = {}
    for token in tokens:
        repo, n = _parse(token)
        if repo is None and named:
            repo = next(iter(named)) if len(named) == 1 else UNKNOWN
        out.setdefault((repo, n), token)
    return list(out.items())


def refs_in(sentence: str, known: frozenset[str] = frozenset()) -> list[tuple[Ref, str]]:
    return _resolve(_REF_RE.findall(sentence), sentence, known)


def merged_in(sentence: str, known: frozenset[str] = frozenset()) -> list[Ref]:
    """The pull requests ``sentence`` says have merged (not will, not might)."""
    if _MERGE_NOT_YET.search(sentence):
        return []
    tokens = [m.group("ref") for p in _MERGED for m in p.finditer(sentence)]
    return [ref for ref, _ in _resolve(tokens, sentence, known)]


def _same(claim: Ref, other: Ref, records: _Records, *, strict: bool) -> bool:
    """Whether ``other`` is the pull request ``claim`` is about."""
    (repo, n), (other_repo, other_n) = claim, other
    if n != other_n:
        return False
    if UNKNOWN in (repo, other_repo):
        return not strict
    if repo == other_repo:
        return True
    if repo is None or other_repo is None:
        if not strict:
            return True
        named = other_repo if repo is None else repo
        return records.reported.get(n) == {named}
    return False


def episode_of(record: TranscriptRecord) -> str | None:
    """The episode (thread or room channel) a record was said in."""
    message = ((record.content.get("l9") or {}).get("header") or {}).get("message") or {}
    episode = message.get("episode")
    return episode if isinstance(episode, str) else None


def _payload(record: TranscriptRecord) -> tuple[str | None, dict[str, Any]]:
    payload = (record.content.get("l9") or {}).get("payload") or {}
    return payload.get("type"), payload.get("data") or {}


def _history(records: list[TranscriptRecord], before: datetime) -> _Records:
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
            ref = _parse(str(data.get("ref") or ""))
            if ref[1]:
                when = parse_recorded_at(str(data.get("at") or "")) or at
                upstream.append(_Upstream(str(data.get("change") or ""), ref, when, r.message_id))
    reported: dict[str, set[str]] = {}
    for u in upstream:
        if u.ref[0]:
            reported.setdefault(u.ref[1], set()).add(u.ref[0])
    known = {repo for repo, _ in (u.ref for u in upstream) if repo}
    for s in said:
        known |= {r for r, _ in (_parse(t) for t in _REF_RE.findall(s.text)) if r}
    return _Records(said, upstream, frozenset(known), reported)


def _approved(ref: Ref, speaker: str, thread: str | None, records: _Records) -> bool:
    """Whether someone other than ``speaker`` approved ``ref`` in this room.

    In a task's own thread an approval counts without naming the number
    ("approved, CI passes"), as long as the message names no other pull request:
    that is how reviewers approve in a thread.
    """
    if any(
        u.change == "approved" and _same(ref, u.ref, records, strict=False)
        for u in records.upstream
    ):
        return True
    in_thread = thread is not None and not thread.endswith((":live", ":knowledge"))
    for s in records.said:
        if s.sender == speaker:
            continue
        mentioned = [r for r, _ in refs_in(s.text, records.known)]
        same_thread = (
            in_thread
            and s.episode == thread
            and all(_same(ref, r, records, strict=False) for r in mentioned)
        )
        for sentence in _SENTENCES.split(s.text):
            if not _APPROVAL_WORDS.search(sentence) or _NEGATED.search(sentence):
                continue
            here = [r for r, _ in refs_in(sentence, records.known)]
            if any(_same(ref, r, records, strict=False) for r in here) or (
                same_thread and not here
            ):
                return True
    return False


def _merged_at(ref: Ref, records: _Records) -> tuple[datetime, str, str] | None:
    merges = [
        (u.at, u.record_id, "GitHub")
        for u in records.upstream
        if u.change == "merged" and _same(ref, u.ref, records, strict=True)
    ]
    for s in records.said:
        for sentence in _SENTENCES.split(s.text):
            if any(_same(ref, m, records, strict=True) for m in merged_in(sentence, records.known)):
                merges.append((s.at, s.message_id, f"@{s.sender}"))
                break
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
    if not _REF_RE.search(sentence):
        return []
    history = _history(records, at)
    refs = [(r, t) for r, t in refs_in(sentence, history.known) if r[0] != UNKNOWN]
    if not refs:
        return []
    findings: list[Finding] = []

    open_refs: dict[Ref, str] = {}
    for pattern in _OPEN:
        for m in pattern.finditer(sentence):
            for ref, _ in _resolve([m.group("ref")], sentence, history.known):
                if ref[0] != UNKNOWN:
                    open_refs.setdefault(ref, m.group(0))
    says_merged = merged_in(sentence, history.known)
    for ref, words in open_refs.items():
        if ref in says_merged:
            continue
        merged = _merged_at(ref, history)
        if merged and merged[0] < at - GRACE:
            when, record_id, source = merged
            findings.append(
                Finding(
                    claim="open",
                    ref=label(ref),
                    sure=True,
                    line=f"{label(ref)} was already merged, at {when:%H:%M}.",
                    quotes=[words],
                    sentence=sentence,
                    checked=[
                        {
                            "what": f"merges of {label(ref)} in this room",
                            "found": f"merged at {when:%H:%M} ({source})",
                            "id": record_id,
                            "at": when.isoformat(),
                        }
                    ],
                )
            )

    words = _APPROVAL_WORDS.search(sentence)
    approval_claimed = ("approval" in kinds or words) and not _NEGATED.search(sentence)
    if approval_claimed and words and not _OWN_APPROVAL.search(sentence):
        for ref, token in refs:
            if ref in open_refs or _approved(ref, speaker, thread, history):
                continue
            findings.append(
                Finding(
                    claim="approval",
                    ref=label(ref),
                    sure=False,
                    line=f"Can't find an approval for {label(ref)}.",
                    quotes=[token, words.group(0)],
                    sentence=sentence,
                    checked=[{"what": f"approvals of {label(ref)} in this room", "found": "none"}],
                )
            )
    return findings
