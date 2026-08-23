# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GitHubProvider.fetch`` executed end to end against a fake transport.

Every other status test drives ``RecordingProvider`` or the pure mapping helpers.
The fetch path itself (building the aliased GraphQL document, walking each alias
back to one outcome per ref, and the rate-limit and not-visible branches) had
never run. These are the file every future provider is copied from, so they run
it here, with a fake ``httpx`` transport rather than the network.

A fake transport can only prove the code walks a response, not that GitHub
answers the document the way we think. So one test pins the *document*: it must
ask for each pull request by identity, never regress to the free-text issue
search a batch built from bare numbers would send. Settling that against the live
API still needs a real token.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services.status.context import HttpContext
from app.services.status.providers.github import GitHubProvider
from app.services.status.runtime import StatusRuntime
from app.services.status.types import FetchFailed, FetchSucceeded, Ref

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

#: An alias whose repository itself did not resolve (``data.rN`` is null), as
#: opposed to one whose repository resolved but the pull request did not.
REPO_NULL = object()


def ref(ident: str) -> Ref:
    return Ref(provider="github", kind="pull_request", id=ident)


def pr_node(
    *,
    state: str = "OPEN",
    is_draft: bool = False,
    review: str | None = None,
    rollup: str | None = None,
    updated_at: str = "2026-08-22T11:30:00Z",
) -> dict:
    """A PullRequest node shaped like GitHub's GraphQL result for one alias."""
    commits = (
        {"nodes": [{"commit": {"statusCheckRollup": {"state": rollup}}}]}
        if rollup is not None
        else {"nodes": []}
    )
    return {
        "url": "https://github.com/o/r/pull/1",
        "title": "a pull request",
        "state": state,
        "isDraft": is_draft,
        "updatedAt": updated_at,
        "reviewDecision": review,
        "commits": commits,
    }


def aliased_response(
    entries: list, *, status: int = 200, errors: list | None = None
) -> httpx.Response:
    """Build ``{"data": {"r0": ..., "r1": ...}}`` aligned to the refs' order.

    Each entry is a node dict (the pull request resolved), ``None`` (the repo
    resolved but the pull request did not), or ``REPO_NULL`` (the repo itself
    did not resolve, so the whole alias is null).
    """
    data: dict = {}
    for i, entry in enumerate(entries):
        data[f"r{i}"] = None if entry is REPO_NULL else {"pullRequest": entry}
    body: dict = {"data": data}
    if errors is not None:
        body["errors"] = errors
    return httpx.Response(status, json=body)


def context_returning(handler) -> HttpContext:
    """An ``HttpContext`` whose transport answers from ``handler``, never a socket."""
    client = httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    return HttpContext(client)


@pytest.mark.asyncio
async def test_the_document_asks_for_each_pull_request_by_identity_not_search():
    # The guard for the whole batching claim: identity lookups, one alias per
    # ref, never the free-text issue search that matches a number as body text.
    refs = [ref("mycelium-io/mycelium#504"), ref("acme/tools#502")]
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["doc"] = json.loads(request.content)["query"]
        return aliased_response([pr_node(review="APPROVED"), pr_node()])

    ctx = context_returning(handler)
    await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    doc = seen["doc"]
    assert 'repository(owner: "mycelium-io", name: "mycelium")' in doc
    assert "pullRequest(number: 504)" in doc
    assert 'repository(owner: "acme", name: "tools")' in doc
    assert "pullRequest(number: 502)" in doc
    assert "search(" not in doc
    assert "type: ISSUE" not in doc


@pytest.mark.asyncio
async def test_the_happy_path_answers_one_outcome_per_ref_with_states_mapped():
    refs = [
        ref("mycelium-io/mycelium#504"),
        ref("mycelium-io/mycelium#502"),
        ref("mycelium-io/mycelium#500"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return aliased_response(
            [
                pr_node(review="APPROVED", rollup="SUCCESS"),
                pr_node(review="CHANGES_REQUESTED"),
                pr_node(state="MERGED"),
            ]
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    approved, changes, merged = outcomes
    assert isinstance(approved, FetchSucceeded)
    assert isinstance(changes, FetchSucceeded)
    assert isinstance(merged, FetchSucceeded)
    # Outcomes stay aligned to the refs they were asked for.
    assert [o.ref for o in outcomes] == refs
    assert approved.upstream.state == "ok"
    assert approved.upstream.label == "approved"
    assert changes.upstream.state == "blocked"
    assert changes.upstream.label == "changes requested"
    # A merged PR is done, and its answer is cached far longer than an open one.
    assert merged.upstream.state == "done"
    assert merged.ttl == timedelta(days=1)


@pytest.mark.asyncio
async def test_a_ref_the_token_cannot_see_is_erred_not_the_whole_batch():
    refs = [ref("mycelium-io/mycelium#504"), ref("acme/private#7")]

    def handler(request: httpx.Request) -> httpx.Response:
        # The public one resolves; the private repo's alias comes back null.
        return aliased_response([pr_node(review="APPROVED"), REPO_NULL])

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    assert isinstance(outcomes[0], FetchSucceeded)
    missing = outcomes[1]
    assert isinstance(missing, FetchFailed)
    assert "not visible" in missing.reason


@pytest.mark.asyncio
async def test_one_partial_node_does_not_sink_the_healthy_answers_beside_it():
    # A structurally thin node (only a state, everything else absent) must map
    # conservatively, never raise and take its whole chunk down with it.
    refs = [ref("mycelium-io/mycelium#504"), ref("mycelium-io/mycelium#502")]

    def handler(request: httpx.Request) -> httpx.Response:
        return aliased_response([pr_node(review="APPROVED"), {"state": "OPEN"}])

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    assert isinstance(outcomes[0], FetchSucceeded)
    thin = outcomes[1]
    assert isinstance(thin, FetchSucceeded)
    assert thin.upstream.state == "pending"


@pytest.mark.asyncio
async def test_a_secondary_rate_limit_sets_retry_after_from_the_reset_header():
    refs = [ref("mycelium-io/mycelium#504"), ref("mycelium-io/mycelium#502")]
    reset_at = datetime.now(UTC) + timedelta(minutes=17)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-reset": str(int(reset_at.timestamp()))},
            text="You have exceeded a secondary rate limit",
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    # Honoured from the reset header (~17m), distinctly not the 5m fallback guess.
    for outcome in outcomes:
        assert isinstance(outcome, FetchFailed)
        assert outcome.reason == "rate limited"
        assert outcome.retry_after is not None
        assert timedelta(minutes=15) < outcome.retry_after < timedelta(minutes=18)


@pytest.mark.asyncio
async def test_the_primary_graphql_rate_limit_arrives_as_a_200_and_is_still_caught():
    # The primary GraphQL limit is a 200 whose errors carry RATE_LIMITED, with a
    # Retry-After. Sniffing body text for a 403 would miss it entirely.
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"retry-after": "120"},
            json={"data": None, "errors": [{"type": "RATE_LIMITED", "message": "API rate limit"}]},
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    outcome = outcomes[0]
    assert isinstance(outcome, FetchFailed)
    assert outcome.reason == "rate limited"
    assert outcome.retry_after == timedelta(seconds=120)


@pytest.mark.asyncio
async def test_a_graphql_error_with_null_data_errs_every_ref_rather_than_fabricating():
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": None, "errors": [{"message": "Something went wrong"}]}
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    assert isinstance(outcomes[0], FetchFailed)


@pytest.mark.asyncio
async def test_a_4xx_that_is_not_a_rate_limit_errs_the_batch_with_the_code():
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    outcome = outcomes[0]
    assert isinstance(outcome, FetchFailed)
    assert "401" in outcome.reason


@pytest.mark.asyncio
async def test_a_present_but_bare_node_is_conservative_never_fabricated_as_healthy():
    # An open PR with no review yet and no checks reported: the honest answer is
    # "in motion, nobody required", not a fabricated "ok" or "done".
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return aliased_response([pr_node()])

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    outcome = outcomes[0]
    assert isinstance(outcome, FetchSucceeded)
    assert outcome.upstream.state == "pending"
    assert outcome.upstream.state not in ("ok", "done")


@pytest.mark.asyncio
async def test_when_fetch_raises_the_runtime_marks_the_whole_chunk_errored():
    # The provider can't map what it never received, and the runtime can't know
    # which refs in the chunk survived, so a transport failure errs all of them.
    refs = [ref("mycelium-io/mycelium#504"), ref("mycelium-io/mycelium#502")]

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    provider = GitHubProvider()
    rt = StatusRuntime(
        providers={provider.name: provider},
        context_factory=lambda p, credential: context_returning(handler),
        credentials={"GITHUB_TOKEN": "token"},
    )
    answers = await rt.resolve(refs, NOW)
    await rt.aclose()

    assert all(answers[r].freshness == "error" for r in refs)
    assert all("raised" in (answers[r].error or "") for r in refs)
