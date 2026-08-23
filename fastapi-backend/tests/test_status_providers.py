# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The properties the status contract is worth having for.

Each test here is a claim the design makes: reads never fetch, fetches are bulk,
one bad ref doesn't sink a batch, a stale answer is served rather than withheld,
and nothing is handed to a caller without its age.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.services.status.auth import Bearer
from app.services.status.cache import StatusCache
from app.services.status.providers.github import GitHubProvider, _liveness
from app.services.status.runtime import StatusRuntime
from app.services.status.types import Err, Liveness, Ok, Ref

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class FakeContext:
    """A provider is handed a transport, never a credential."""

    def __init__(self, http: object | None = None) -> None:
        self.logs: list[str] = []
        self.http = http

    def log(self, message: str, **fields: object) -> None:
        self.logs.append(message)


def fake_factory(provider: object, auth: object) -> FakeContext:
    """Stand in for the real per-provider context factory. The provider under
    test here never touches ``ctx.http``; what matters is the runtime asks for
    one context per provider and passes it down, not what it holds."""
    return FakeContext()


class RecordingProvider:
    """Counts calls, so a test can prove batching rather than assume it."""

    name = "fake"
    base_url = "https://example.invalid"
    auth = None
    ttl = timedelta(minutes=5)
    swr = timedelta(minutes=30)

    def __init__(
        self, max_batch: int = 10, fail: set[str] | None = None, raises: bool = False
    ) -> None:
        self.max_batch = max_batch
        self.calls: list[list[Ref]] = []
        self._fail = fail or set()
        self._raises = raises

    def claims(self, text: str) -> list[Ref]:
        words = (word.strip(".,;:") for word in text.split())
        return [Ref(provider=self.name, kind="task", id=w) for w in words if w.startswith("T-")]

    async def fetch(self, refs, ctx):
        self.calls.append(list(refs))
        if self._raises:
            raise RuntimeError("provider exploded")
        return [
            Err(ref=ref, reason="gone")
            if ref.id in self._fail
            else Ok(ref=ref, liveness=Liveness(state="ok", label="done"))
            for ref in refs
        ]


def ref(ident: str) -> Ref:
    return Ref(provider="fake", kind="task", id=ident)


def runtime(provider, **kw) -> StatusRuntime:
    return StatusRuntime(providers={provider.name: provider}, context_factory=fake_factory, **kw)


class TestReadPath:
    def test_a_read_never_fetches(self):
        provider = RecordingProvider()
        rt = runtime(provider)
        answers = rt.read([ref("T-1")], NOW)
        assert provider.calls == []
        assert answers[ref("T-1")].freshness == "missing"

    @pytest.mark.asyncio
    async def test_a_fresh_value_is_served_without_refetching(self):
        provider = RecordingProvider()
        rt = runtime(provider)
        await rt.refresh([ref("T-1")], NOW)
        await rt.refresh([ref("T-1")], NOW + timedelta(minutes=1))
        assert len(provider.calls) == 1
        assert rt.read([ref("T-1")], NOW + timedelta(minutes=1))[ref("T-1")].freshness == "fresh"

    @pytest.mark.asyncio
    async def test_a_stale_value_is_still_served_and_marked(self):
        provider = RecordingProvider()
        rt = runtime(provider)
        await rt.refresh([ref("T-1")], NOW)
        later = NOW + timedelta(minutes=10)
        known = rt.read([ref("T-1")], later)[ref("T-1")]
        assert known.freshness == "stale"
        assert known.liveness is not None
        assert known.age(later) == timedelta(minutes=10)
        assert rt.due([ref("T-1")], later) == [ref("T-1")]

    @pytest.mark.asyncio
    async def test_past_the_stale_window_it_stops_being_evidence(self):
        provider = RecordingProvider()
        rt = runtime(provider)
        await rt.refresh([ref("T-1")], NOW)
        known = rt.read([ref("T-1")], NOW + timedelta(hours=2))[ref("T-1")]
        assert known.freshness == "missing"
        assert known.liveness is None

    @pytest.mark.asyncio
    async def test_a_caller_may_impose_its_own_tolerance(self):
        provider = RecordingProvider()
        rt = runtime(provider)
        await rt.refresh([ref("T-1")], NOW)
        later = NOW + timedelta(minutes=3)
        assert rt.read([ref("T-1")], later)[ref("T-1")].freshness == "fresh"
        strict = rt.read([ref("T-1")], later, max_age=timedelta(minutes=1))[ref("T-1")]
        assert strict.freshness == "missing"
        assert strict.liveness is None

    def test_a_ref_with_no_provider_is_answered_not_dropped(self):
        rt = runtime(RecordingProvider())
        orphan = Ref(provider="asana", kind="task", id="123")
        known = rt.read([orphan], NOW)[orphan]
        assert known.freshness == "missing"
        assert "no provider" in (known.error or "")


class TestBulk:
    @pytest.mark.asyncio
    async def test_a_hundred_refs_cost_ten_calls_not_a_hundred(self):
        provider = RecordingProvider(max_batch=10)
        rt = runtime(provider)
        await rt.refresh([ref(f"T-{i}") for i in range(100)], NOW)
        assert len(provider.calls) == 10
        assert all(len(call) <= 10 for call in provider.calls)

    @pytest.mark.asyncio
    async def test_refs_are_grouped_by_provider(self):
        one, two = RecordingProvider(), RecordingProvider()
        two.name = "other"
        rt = StatusRuntime(providers={"fake": one, "other": two}, context_factory=fake_factory)
        await rt.refresh([ref("T-1"), Ref(provider="other", kind="task", id="T-2")], NOW)
        assert len(one.calls) == 1
        assert len(two.calls) == 1

    @pytest.mark.asyncio
    async def test_one_dead_ref_does_not_sink_its_batch(self):
        provider = RecordingProvider(fail={"T-2"})
        rt = runtime(provider)
        refs = [ref("T-1"), ref("T-2"), ref("T-3")]
        answers = await rt.resolve(refs, NOW)
        assert answers[ref("T-1")].liveness is not None
        assert answers[ref("T-3")].liveness is not None
        assert answers[ref("T-2")].freshness == "error"

    @pytest.mark.asyncio
    async def test_a_provider_that_raises_marks_its_chunk_and_spares_the_rest(self):
        broken, fine = RecordingProvider(raises=True), RecordingProvider()
        fine.name = "other"
        rt = StatusRuntime(providers={"fake": broken, "other": fine}, context_factory=fake_factory)
        other = Ref(provider="other", kind="task", id="T-9")
        answers = await rt.resolve([ref("T-1"), other], NOW)
        assert answers[ref("T-1")].freshness == "error"
        assert "exploded" in (answers[ref("T-1")].error or "")
        assert answers[other].liveness is not None

    @pytest.mark.asyncio
    async def test_a_ref_the_provider_forgot_is_not_left_pending_forever(self):
        class Forgetful(RecordingProvider):
            async def fetch(self, refs, ctx):
                self.calls.append(list(refs))
                return [Ok(ref=refs[0], liveness=Liveness(state="ok", label="done"))]

        rt = runtime(Forgetful())
        answers = await rt.resolve([ref("T-1"), ref("T-2")], NOW)
        assert answers[ref("T-2")].freshness == "error"
        assert "no outcome" in (answers[ref("T-2")].error or "")


class TestCoalescing:
    @pytest.mark.asyncio
    async def test_concurrent_refreshes_of_one_ref_make_one_call(self):
        import asyncio

        provider = RecordingProvider()
        rt = runtime(provider)
        await asyncio.gather(*(rt.refresh([ref("T-1")], NOW) for _ in range(5)))
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_a_rate_limited_provider_is_left_alone_until_it_says_otherwise(self):
        class Limited(RecordingProvider):
            async def fetch(self, refs, ctx):
                self.calls.append(list(refs))
                return [
                    Err(ref=r, reason="rate limited", retry_after=timedelta(minutes=10))
                    for r in refs
                ]

        provider = Limited()
        rt = runtime(provider)
        await rt.refresh([ref("T-1")], NOW)
        await rt.refresh([ref("T-1")], NOW + timedelta(minutes=1))
        assert len(provider.calls) == 1
        assert rt.due([ref("T-1")], NOW + timedelta(minutes=11)) == [ref("T-1")]

    @pytest.mark.asyncio
    async def test_a_failed_refresh_keeps_the_last_thing_that_worked(self):
        cache = StatusCache()
        cache.put_ok(ref("T-1"), Liveness(state="ok", label="green"), NOW)
        cache.put_err(ref("T-1"), "boom", NOW + timedelta(minutes=1))
        entry = cache.known(
            ref("T-1"), NOW + timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30)
        )
        assert entry.liveness is not None
        assert entry.liveness.label == "green"
        assert entry.error == "boom"


class TestClaims:
    def test_the_app_knows_no_syntax_only_providers_do(self):
        rt = runtime(RecordingProvider())
        assert [r.id for r in rt.claims("blocked on T-7 and T-9, ignore #504")] == ["T-7", "T-9"]

    def test_github_claims_both_a_slug_and_a_pasted_url(self):
        provider = GitHubProvider()
        found = provider.claims(
            "see mycelium-io/mycelium#504 and https://github.com/mycelium-io/mycelium/pull/502"
        )
        assert [r.id for r in found] == ["mycelium-io/mycelium#502", "mycelium-io/mycelium#504"]
        assert all(r.kind == "pull_request" for r in found)

    def test_the_same_reference_twice_is_one_ref(self):
        provider = GitHubProvider()
        found = provider.claims("a/b#1 and again a/b#1")
        assert len(found) == 1

    def test_the_provider_declares_its_credential_rather_than_reading_one(self):
        provider = GitHubProvider()
        # The provider names its credential through a scheme, never a value: the
        # scheme says GitHub takes a bearer token called GITHUB_TOKEN.
        assert provider.auth.names() == ("GITHUB_TOKEN",)
        # A provider that cannot read a credential cannot leak one, and the
        # file people copy shouldn't teach them to handle auth at all.
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/services/status/providers/github.py"
        ).read_text()
        assert "Authorization" not in source
        assert "ctx.secret" not in source


class TestCredentials:
    """A declared credential is the runtime's to resolve, and to refuse."""

    class Guarded(RecordingProvider):
        auth = Bearer("FAKE_TOKEN")

    @pytest.mark.asyncio
    async def test_a_provider_missing_its_credential_is_never_called(self):
        provider = self.Guarded()
        rt = StatusRuntime(providers={provider.name: provider}, context_factory=fake_factory)
        answers = await rt.resolve([ref("T-1")], NOW)
        assert provider.calls == []
        assert answers[ref("T-1")].freshness == "error"
        assert "FAKE_TOKEN not configured" in (answers[ref("T-1")].error or "")

    @pytest.mark.asyncio
    async def test_a_resolved_credential_lets_the_provider_run(self):
        provider = self.Guarded()
        rt = StatusRuntime(
            providers={provider.name: provider},
            context_factory=fake_factory,
            credentials={"FAKE_TOKEN": "s3cret"},
        )
        answers = await rt.resolve([ref("T-1")], NOW)
        assert len(provider.calls) == 1
        assert answers[ref("T-1")].liveness is not None

    @pytest.mark.asyncio
    async def test_one_unconfigured_provider_does_not_stop_the_others(self):
        guarded, open_provider = self.Guarded(), RecordingProvider()
        open_provider.name = "other"
        rt = StatusRuntime(
            providers={"fake": guarded, "other": open_provider}, context_factory=fake_factory
        )
        other = Ref(provider="other", kind="task", id="T-9")
        answers = await rt.resolve([ref("T-1"), other], NOW)
        assert answers[ref("T-1")].freshness == "error"
        assert answers[other].liveness is not None


class TestStateVocabulary:
    """`ok` and `done` are the pair readers conflate, so pin them down."""

    def test_github_never_reports_an_open_pull_request_as_done(self):
        node = {"state": "OPEN", "reviewDecision": "APPROVED", "commits": {"nodes": []}}
        status = _liveness(node)
        assert status.state == "ok"
        assert status.label == "approved"

    def test_a_merged_pull_request_is_done_not_ok(self):
        assert _liveness({"state": "MERGED"}).state == "done"

    def test_a_closed_one_is_also_done_and_the_label_carries_how_it_ended(self):
        closed = _liveness({"state": "CLOSED"})
        assert closed.state == "done"
        assert closed.label == "closed"

    def test_green_checks_alone_are_not_ok(self):
        node = {
            "state": "OPEN",
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        }
        assert _liveness(node).state == "pending"

    def test_a_person_blocks_and_a_machine_fails(self):
        person = {"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED"}
        machine = {
            "state": "OPEN",
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
        }
        assert _liveness(person).state == "blocked"
        assert _liveness(machine).state == "failed"


class TestFieldNameCollision:
    """A provider's answer must not shadow the board row's own `status`.

    The row owns `status` for its lifecycle; a provider answers about the
    external thing the row points at. Both vocabularies contain `blocked`,
    meaning different things, so the answer lands under its own field
    (`ROW_FIELD`) and is named `liveness` in the contract, never `status`.
    """

    def test_the_provider_answer_lands_under_its_own_row_field_not_status(self):
        from app.services.status.types import ROW_FIELD

        assert ROW_FIELD == "upstream"
        # `status` is the row's lifecycle; `live` is the boolean the projections
        # already put on a row for agent presence, read as `fields.live === true`
        # and inferred as a checkbox. Landing an object on either is the same bug.
        assert ROW_FIELD not in ("status", "live")

    def test_the_two_vocabularies_overlap_only_on_blocked(self):
        import json
        import typing

        from app.services.status.types import LiveState

        board = json.loads(
            (
                pathlib.Path(__file__).resolve().parents[2] / "contracts/board-vocabulary.json"
            ).read_text()
        )
        live = set(typing.get_args(LiveState))
        row = set(board["statuses"])
        # The one shared word is exactly why they must not share a field.
        assert live & row == {"blocked"}

    def test_the_contract_type_is_named_for_liveness_not_status(self):
        # The dataclass a provider returns is `Liveness`; a `Status` next to a
        # row's `status` field is the collision this rename removes.
        from app.services.status import types

        assert hasattr(types, "Liveness")
        assert not hasattr(types, "Status")
