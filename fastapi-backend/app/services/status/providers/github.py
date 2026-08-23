# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GitHub pull requests, as the worked example of a provider.

This exists to be copied.  It is deliberately the whole of what a provider
author writes: claim a syntax, resolve a batch, map the tool's vocabulary onto
the six states.  There is no auth code, no retry loop and no cache in here —
those belong to the runtime, and a provider that reimplements them is doing the
harness's job badly.

The batching is the part worth reading.  One GraphQL document resolves up to
fifty pull requests in a single request, which is the difference between a board
of fifty rows costing one call and costing fifty.  A provider that can only
fetch one at a time is still legitimate; it declares ``max_batch = 1`` and the
runtime paces it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.services.status.auth import Bearer
from app.services.status.types import (
    FetchFailed,
    FetchOutcome,
    FetchSucceeded,
    ProviderContext,
    Ref,
    UpstreamState,
)

#: ``owner/repo#123`` and the pasted browser URL, which is what people have on
#: their clipboard when they are talking about a pull request.
_SLUG = re.compile(r"\b([\w.-]+)/([\w.-]+)#(\d+)\b")
_URL = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")

#: GitHub's states are richer than the board's; this is where the loss is made
#: explicit rather than hidden in a template somewhere.
_STATE = {
    "MERGED": "done",
    "CLOSED": "done",
    "SUCCESS": "ok",
    "PENDING": "pending",
    "FAILURE": "failed",
    "ERROR": "failed",
}

#: The fields one pull request contributes. Shared by every alias in a batch.
_FRAGMENT = """
fragment pr on PullRequest {
  url title state isDraft updatedAt
  reviewDecision
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
}
"""


def _document(refs: list[Ref]) -> str:
    """One aliased ``repository/pullRequest`` lookup per ref, in a single query.

    Each ref is asked for by identity ``(owner, name, number)``, not by search.
    GitHub's issue search has no "number equals" qualifier, so a bare number
    there matches free text in title and body and several ``repo:`` qualifiers
    OR together; a batch built that way answers the wrong question. Aliases ask
    for each pull request exactly, still in one request, and a ref the token
    cannot see comes back as a null alias rather than a missing search hit.
    """
    aliases = []
    for i, ref in enumerate(refs):
        repo_part, number = ref.id.split("#")
        owner, name = repo_part.split("/")
        aliases.append(
            f"  r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) "
            f"{{ pullRequest(number: {int(number)}) {{ ...pr }} }}"
        )
    return "query {\n" + "\n".join(aliases) + "\n}\n" + _FRAGMENT


class GitHubProvider:
    name = "github"
    base_url = "https://api.github.com"
    #: Declared, never read. GitHub takes a bearer token; the runtime resolves
    #: ``GITHUB_TOKEN`` and hands back a transport that already carries it, so
    #: this class never sees the value.
    auth = Bearer("GITHUB_TOKEN")
    #: Kept modest so one aliased document stays well inside GitHub's query node
    #: and complexity limits. Chunking to it is the runtime's job.
    max_batch = 50
    #: A pull request people are actively looking at moves on the order of
    #: minutes; a minute of staleness is cheaper than the rate limit.
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def claims(self, text: str) -> list[Ref]:
        refs: list[Ref] = []
        seen: set[str] = set()
        for match in (*_URL.finditer(text), *_SLUG.finditer(text)):
            owner, repo, number = match.group(1), match.group(2), match.group(3)
            ident = f"{owner}/{repo}#{number}"
            if ident in seen:
                continue
            seen.add(ident)
            refs.append(
                Ref(
                    provider=self.name,
                    kind="pull_request",
                    id=ident,
                    url=f"https://github.com/{owner}/{repo}/pull/{number}",
                )
            )
        return refs

    async def fetch(self, refs: list[Ref], ctx: ProviderContext) -> list[FetchOutcome]:
        # No auth here: a provider that is called at all has its credential, and
        # ``ctx.http`` is already bound to ``base_url`` carrying it.
        response = await ctx.http.post("/graphql", json={"query": _document(refs)})

        # GraphQL reports its primary rate limit as a 200 with a RATE_LIMITED
        # error, and secondary limits as 403/429; both are honoured, not sniffed
        # from body text alone.
        if _is_rate_limited(response):
            wait = _retry_after(response) or timedelta(minutes=5)
            return [FetchFailed(ref=ref, reason="rate limited", retry_after=wait) for ref in refs]
        if response.status_code >= 400:
            return [FetchFailed(ref=ref, reason=f"github {response.status_code}") for ref in refs]

        data = response.json().get("data") or {}
        outcomes: list[FetchOutcome] = []
        for i, ref in enumerate(refs):
            alias = data.get(f"r{i}")
            node = alias.get("pullRequest") if isinstance(alias, dict) else None
            if not isinstance(node, dict):
                # A null alias: private, deleted, or outside the token's reach,
                # sometimes with a per-alias GraphQL error beside it. None of
                # them is "no CI", so none is answered as a value.
                outcomes.append(FetchFailed(ref=ref, reason="not visible to this token"))
                continue
            outcomes.append(
                FetchSucceeded(ref=ref, upstream=_upstream_state(node), ttl=_ttl_for(node))
            )
        return outcomes


def _upstream_state(node: dict[str, Any]) -> UpstreamState:
    rollup = _rollup(node)
    if node.get("state") in ("MERGED", "CLOSED"):
        state, label = _STATE[node["state"]], node["state"].lower()
    elif node.get("isDraft"):
        state, label = "pending", "draft"
    elif node.get("reviewDecision") == "CHANGES_REQUESTED":
        state, label = "blocked", "changes requested"
    elif rollup in ("FAILURE", "ERROR"):
        state, label = "failed", "CI failing"
    elif rollup == "PENDING":
        state, label = "pending", "CI running"
    elif node.get("reviewDecision") == "APPROVED":
        state, label = "ok", "approved"
    else:
        state, label = "pending", "awaiting review"

    return UpstreamState(
        state=state,  # type: ignore[arg-type]
        label=label,
        url=node.get("url"),
        source_updated_at=_parse(node.get("updatedAt")),
        detail={"ci": rollup, "review": node.get("reviewDecision"), "title": node.get("title")},
    )


def _ttl_for(node: dict[str, Any]) -> timedelta | None:
    """A settled pull request has stopped moving; stop asking about it."""
    return timedelta(days=1) if node.get("state") in ("MERGED", "CLOSED") else None


def _rollup(node: dict[str, Any]) -> str | None:
    commits = (node.get("commits") or {}).get("nodes") or []
    if not commits:
        return None
    return ((commits[0].get("commit") or {}).get("statusCheckRollup") or {}).get("state")


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _errors(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        return response.json().get("errors") or []
    except (ValueError, AttributeError):
        return []


def _is_rate_limited(response: httpx.Response) -> bool:
    """True for both the primary GraphQL limit and a secondary/abuse limit.

    The primary GraphQL limit arrives as a 200 whose ``errors`` carry a
    ``RATE_LIMITED`` type; a secondary limit arrives as 403 or 429 with a
    ``Retry-After`` or an exhausted ``x-ratelimit-remaining``. Body-text alone
    would miss the first and half of the second.
    """
    if response.status_code in (403, 429):
        return (
            "rate limit" in response.text.lower()
            or response.headers.get("retry-after") is not None
            or response.headers.get("x-ratelimit-remaining") == "0"
        )
    if response.status_code == 200:
        return any(error.get("type") == "RATE_LIMITED" for error in _errors(response))
    return False


def _retry_after(response: httpx.Response) -> timedelta | None:
    """When the server said to come back, taken from its own headers."""
    header = response.headers.get("retry-after")
    if header and header.isdigit():
        return timedelta(seconds=int(header))
    return _until(response.headers.get("x-ratelimit-reset"))


def _until(epoch: str | None) -> timedelta | None:
    if not epoch or not epoch.isdigit():
        return None
    from datetime import UTC

    delta = datetime.fromtimestamp(int(epoch), tz=UTC) - datetime.now(UTC)
    return delta if delta > timedelta(0) else None
