# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GitHubProvider.fetch`` executed end to end against a fake transport.

Every other status test drives ``RecordingProvider`` or the pure mapping helpers.
The fetch path itself (building the GraphQL search query, binding the variable,
walking ``data.search.nodes`` back to one outcome per ref, and the rate-limit and
not-visible branches) had never run. These are the file every future provider is
copied from, so they run it here, with a fake ``httpx`` transport rather than the
network. The response shapes are the shapes GitHub's GraphQL API actually returns.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services.status.context import HttpContext
from app.services.status.providers.github import GitHubProvider
from app.services.status.runtime import StatusRuntime
from app.services.status.types import Err, Ok, Ref

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def ref(ident: str) -> Ref:
    return Ref(provider="github", kind="pull_request", id=ident)


def pr_node(
    ident: str,
    *,
    state: str = "OPEN",
    is_draft: bool = False,
    review: str | None = None,
    rollup: str | None = None,
    updated_at: str = "2026-08-22T11:30:00Z",
) -> dict:
    """A single PullRequest node, shaped like GitHub's GraphQL search result."""
    owner_repo, number = ident.split("#")
    commits = (
        {"nodes": [{"commit": {"statusCheckRollup": {"state": rollup}}}]}
        if rollup is not None
        else {"nodes": []}
    )
    return {
        "number": int(number),
        "url": f"https://github.com/{owner_repo}/pull/{number}",
        "title": f"PR {number}",
        "state": state,
        "isDraft": is_draft,
        "updatedAt": updated_at,
        "repository": {"nameWithOwner": owner_repo},
        "reviewDecision": review,
        "commits": commits,
    }


def search_response(nodes: list[dict], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": {"search": {"nodes": nodes}}})


def context_returning(handler) -> HttpContext:
    """An ``HttpContext`` whose transport answers from ``handler``, never a socket."""
    client = httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    return HttpContext(client)


@pytest.mark.asyncio
async def test_the_happy_path_answers_one_outcome_per_ref_with_states_mapped():
    refs = [
        ref("mycelium-io/mycelium#504"),
        ref("mycelium-io/mycelium#502"),
        ref("mycelium-io/mycelium#500"),
    ]
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return search_response(
            [
                pr_node("mycelium-io/mycelium#504", review="APPROVED", rollup="SUCCESS"),
                pr_node("mycelium-io/mycelium#502", review="CHANGES_REQUESTED"),
                pr_node("mycelium-io/mycelium#500", state="MERGED"),
            ]
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    # The query is one GraphQL document with the search string bound as a variable.
    assert seen["url"].endswith("/graphql")
    assert seen["body"]["variables"]["q"] == (
        "repo:mycelium-io/mycelium 504 repo:mycelium-io/mycelium 502 repo:mycelium-io/mycelium 500"
    )

    by_ref = {o.ref: o for o in outcomes}
    assert all(isinstance(o, Ok) for o in outcomes)
    approved, changes, merged = by_ref[refs[0]], by_ref[refs[1]], by_ref[refs[2]]
    assert isinstance(approved, Ok)
    assert isinstance(changes, Ok)
    assert isinstance(merged, Ok)
    assert approved.liveness.state == "ok"
    assert approved.liveness.label == "approved"
    assert changes.liveness.state == "blocked"
    assert changes.liveness.label == "changes requested"
    # A merged PR is done, and its answer is cached far longer than an open one.
    assert merged.liveness.state == "done"
    assert merged.ttl == timedelta(days=1)


@pytest.mark.asyncio
async def test_a_ref_the_search_did_not_return_is_erred_not_the_whole_batch():
    refs = [ref("mycelium-io/mycelium#504"), ref("acme/private#7")]

    def handler(request: httpx.Request) -> httpx.Response:
        # The private one is outside this token's reach, so GitHub simply omits it.
        return search_response([pr_node("mycelium-io/mycelium#504", review="APPROVED")])

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    by_ref = {o.ref: o for o in outcomes}
    assert isinstance(by_ref[refs[0]], Ok)
    missing = by_ref[refs[1]]
    assert isinstance(missing, Err)
    assert "not visible" in missing.reason


@pytest.mark.asyncio
async def test_a_rate_limit_reply_sets_retry_after_from_the_response_not_a_guess():
    refs = [ref("mycelium-io/mycelium#504"), ref("mycelium-io/mycelium#502")]
    reset_at = datetime.now(UTC) + timedelta(minutes=17)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-reset": str(int(reset_at.timestamp()))},
            text="API rate limit exceeded for installation",
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    # Honoured from the reset header (~17m), distinctly not the 5m fallback guess.
    for outcome in outcomes:
        assert isinstance(outcome, Err)
        assert outcome.reason == "rate limited"
        assert outcome.retry_after is not None
        assert timedelta(minutes=15) < outcome.retry_after < timedelta(minutes=18)


@pytest.mark.asyncio
async def test_a_graphql_error_with_null_data_errs_every_ref_rather_than_fabricating():
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        # A top-level GraphQL failure: data is null, errors carries why.
        return httpx.Response(
            200, json={"data": None, "errors": [{"message": "Something went wrong"}]}
        )

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    assert isinstance(outcomes[0], Err)


@pytest.mark.asyncio
async def test_a_4xx_that_is_not_a_rate_limit_errs_the_batch_with_the_code():
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    outcome = outcomes[0]
    assert isinstance(outcome, Err)
    assert "401" in outcome.reason


@pytest.mark.asyncio
async def test_a_present_but_bare_node_is_conservative_never_fabricated_as_healthy():
    # An open PR with no review yet and no checks reported: the honest answer is
    # "in motion, nobody required", not a fabricated "ok" or "done".
    refs = [ref("mycelium-io/mycelium#504")]

    def handler(request: httpx.Request) -> httpx.Response:
        return search_response([pr_node("mycelium-io/mycelium#504")])

    ctx = context_returning(handler)
    outcomes = await GitHubProvider().fetch(refs, ctx)
    await ctx.aclose()

    outcome = outcomes[0]
    assert isinstance(outcome, Ok)
    assert outcome.liveness.state == "pending"
    assert outcome.liveness.state not in ("ok", "done")


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
