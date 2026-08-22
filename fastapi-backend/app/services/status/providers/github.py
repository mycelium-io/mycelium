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

import re
from datetime import datetime, timedelta
from typing import Any

from app.services.status.types import Context, Err, Ok, Outcome, Ref, Status

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

_QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 50) {
    nodes {
      ... on PullRequest {
        number url title state isDraft updatedAt
        repository { nameWithOwner }
        reviewDecision
        commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      }
    }
  }
}
"""


class GitHubProvider:
    name = "github"
    base_url = "https://api.github.com"
    #: Named, never read. The runtime resolves it and hands back a transport
    #: that already carries it; this class never sees the value.
    credential = "GITHUB_TOKEN"
    #: GitHub's search node cap. Chunking to it is the runtime's job.
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

    async def fetch(self, refs: list[Ref], ctx: Context) -> list[Outcome]:
        # No auth here: a provider that is called at all has its credential, and
        # ``ctx.http`` is already bound to ``base_url`` carrying it.
        query = " ".join(f"repo:{r.id.split('#')[0]} {r.id.split('#')[1]}" for r in refs)
        response = await ctx.http.post(
            "/graphql",
            json={"query": _QUERY, "variables": {"q": query}},
        )

        if response.status_code == 403 and "rate limit" in response.text.lower():
            reset = response.headers.get("x-ratelimit-reset")
            wait = _until(reset) or timedelta(minutes=5)
            return [Err(ref=ref, reason="rate limited", retry_after=wait) for ref in refs]
        if response.status_code >= 400:
            return [Err(ref=ref, reason=f"github {response.status_code}") for ref in refs]

        nodes = (response.json().get("data") or {}).get("search", {}).get("nodes") or []
        found = {f"{n['repository']['nameWithOwner']}#{n['number']}": n for n in nodes if n}

        outcomes: list[Outcome] = []
        for ref in refs:
            node = found.get(ref.id)
            if node is None:
                # Private, deleted, or outside the token's reach — all the same
                # to the reader, and none of them "no CI".
                outcomes.append(Err(ref=ref, reason="not visible to this token"))
                continue
            outcomes.append(Ok(ref=ref, status=_status(node), ttl=_ttl_for(node)))
        return outcomes


def _status(node: dict[str, Any]) -> Status:
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

    return Status(
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


def _until(epoch: str | None) -> timedelta | None:
    if not epoch or not epoch.isdigit():
        return None
    from datetime import UTC

    delta = datetime.fromtimestamp(int(epoch), tz=UTC) - datetime.now(UTC)
    return delta if delta > timedelta(0) else None
