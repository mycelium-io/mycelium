# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The coordination board's projection and schema inference (CLI side).

``contracts/board-vocabulary.json`` freezes the words the GUI and CLI must agree
on; the rest of this file covers the rules that turn room state into rows.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mycelium.board import activity, custody, model
from mycelium.board.model import ItemSource, LiveItem, lens_of
from mycelium.board.projection import project_items
from mycelium.board.schema import groupable_fields, infer_schema
from mycelium.board.upstream import UPSTREAM_STATES, attach_upstream

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def item(item_id: str, **fields) -> LiveItem:
    return LiveItem(id=item_id, title=item_id, source=ItemSource("memory", item_id), fields=fields)


class TestVocabularyContract:
    """The GUI carries its own copy of these; neither may drift silently."""

    def test_statuses_kinds_priorities_match_the_contract(self):
        assert CONTRACT["statuses"] == model.STATUSES
        assert CONTRACT["kinds"] == model.KINDS
        assert CONTRACT["priorities"] == model.PRIORITIES
        assert CONTRACT["lenses"] == model.LENSES
        assert CONTRACT["verbs"] == model.VERBS

    def test_every_status_maps_to_the_contracted_lens(self):
        assert CONTRACT["lens_of_status"] == model.LENS_OF_STATUS
        for status, lens in CONTRACT["lens_of_status"].items():
            assert lens_of(status) == lens

    def test_live_namespaces_match_the_contract(self):
        assert CONTRACT["live_namespaces"] == model.LIVE_NAMESPACES

    def test_folds_a_thread_under_exactly_the_contracted_field_names(self):
        task_contract = CONTRACT["task"]
        assert task_contract["binding_field"] == model.EPISODE_FIELD
        assert task_contract["thread_fields"] == model.THREAD_FIELDS
        assert task_contract["thread_states"] == model.THREAD_STATES
        assert task_contract["task_fields"] == model.TASK_FIELDS

    def test_a_thread_never_writes_one_of_the_unit_s_own_axes(self):
        # The container-outlives-the-negotiation rule, asserted as a
        # disjointness rather than promised in a comment.
        task_contract = CONTRACT["task"]
        assert not set(task_contract["thread_fields"]) & set(task_contract["task_fields"])

    def test_infers_the_type_the_contract_names_for_every_case(self):
        """The same table the GUI suite runs. These two classifiers drifted once,
        so neither may answer differently about the same frontmatter again."""
        for case in CONTRACT["schema"]["cases"]:
            rows = [
                item(f"r{i}", **{case["name"]: value}) for i, value in enumerate(case["values"])
            ]
            found = next(f for f in infer_schema(rows) if f.name == case["name"])
            assert f"{case['name']}: {found.type}" == f"{case['name']}: {case['type']}"
            assert found.type in CONTRACT["schema"]["types"]

    def test_an_out_of_vocabulary_option_sorts_last_as_it_does_in_the_gui(self):
        # A field with a known vocabulary can still hold a value outside it: the
        # room wrote `flaky` where the board knows green/running/red. The stray
        # value belongs after the known ones, not before them.
        rows = [item("a", ci="green"), item("b", ci="green"), item("c", ci="flaky")]
        options = next(f for f in infer_schema(rows) if f.name == "ci").options
        assert [name for name, _ in options] == ["green", "running", "red", "flaky"]

    def test_the_upstream_field_and_its_states_match_the_contract(self):
        assert CONTRACT["upstream"]["states"] == UPSTREAM_STATES
        # Neither of the row's own fields: `status` is the row's lifecycle and
        # `live` is a boolean for agent presence.
        assert CONTRACT["upstream"]["field"] not in ("status", "live")

    def test_every_field_attach_writes_is_one_the_contract_names(self):
        """Asserted against what the code writes, not against a copy of it.

        The contract's companion list drifted the moment two fields were added
        without touching it, because nothing recomputed it. This drives every
        branch of `attach_upstream` and compares the keys that actually appear.
        """
        rows = [
            item("resolved"),
            item("pending"),
            item("two-refs"),
            item("errored"),
        ]
        attach_upstream(
            rows,
            status_payload(
                answer("a", "ok", "approved", url="https://x", age_seconds=30),
                answer("b", None, freshness="missing"),
                answer("c", "failed", "CI failing"),
                answer("d", "unknown", None, error="not visible to this token"),
                rows={
                    "resolved": ["a"],
                    "pending": ["b"],
                    "two-refs": ["a", "c"],
                    "errored": ["d"],
                },
            ),
        )
        written = {key for row in rows for key in row.fields}
        expected = {CONTRACT["upstream"]["field"], *CONTRACT["upstream"]["companion_fields"]}
        assert written == expected


class TestProjection:
    #: The two rows an agreement compiles into: one open and assigned, one done.
    work = [
        {
            "key": "work/flip-reads-behind-a-flag",
            "value": "flip reads behind a flag",
            "updated_at": "2026-08-20T10:00:00Z",
            "updated_by": "aligner",
            "meta": {"kind": "action", "status": "open", "assignee": "@growth"},
        },
        {
            "key": "work/retire-the-legacy-store",
            "value": "retire the legacy store",
            "updated_at": "2026-08-20T10:00:00Z",
            "updated_by": "aligner",
            "meta": {"kind": "action", "status": "resolved", "assignee": "@risk"},
        },
    ]

    def project(
        self,
        *,
        episodes: list[dict] | None = None,
        memories: list[dict] | None = None,
        agents: list[dict] | None = None,
        members: list[dict] | None = None,
    ) -> list[LiveItem]:
        return project_items(
            episodes=episodes or [],
            memories=self.work if memories is None else memories,
            agents=agents or [],
            members=members or [],
            now=NOW,
        )

    def test_a_compiled_task_names_who_it_is_for_without_claiming_it(self):
        rows = self.project()
        assert rows[0].title == "flip reads behind a flag"
        assert rows[0].get("assignee") == "@growth"
        # An assignment is not a claim: the row stays unclaimed until somebody
        # takes it, so nothing asserts a holder who never agreed to hold it.
        assert rows[0].status == "open"
        assert custody.custody_of(rows[0], NOW) == "unclaimed"

    def test_a_done_task_resolves(self):
        assert self.project()[1].status == "resolved"

    def test_every_row_carries_its_provenance(self):
        assert self.project()[0].source.label == "work/flip-reads-behind-a-flag"

    def test_only_coordination_namespaces_become_rows(self):
        memories = [
            {
                "key": "decisions/cutover",
                "value": "Phased cutover.",
                "created_by": "aligner",
                "updated_at": "2026-08-22T09:00:00Z",
            },
            {
                "key": "context/goal",
                "value": "Zero downtime.",
                "created_by": "operator",
                "updated_at": "2026-08-22T09:00:00Z",
            },
        ]
        rows = [r for r in self.project(memories=memories) if r.id.startswith("memory:")]
        assert [r.id for r in rows] == ["memory:decisions/cutover"]

    def test_a_memory_frontmatter_field_passes_through_as_a_column(self):
        memories = [
            {
                "key": "work/rotate-keys",
                "value": {
                    "text": "Rotate the signing keys",
                    "title": "Rotate the signing keys",
                    "severity": "sev2",
                },
                "created_by": "julia",
                "updated_at": "2026-08-22T09:00:00Z",
            }
        ]
        row = next(r for r in self.project(memories=memories) if r.id.startswith("memory:"))
        assert row.fields["severity"] == "sev2"
        assert row.title == "Rotate the signing keys"

    def test_a_resident_agent_is_a_row_and_a_registered_one_is_not(self):
        agents = [
            {"handle": "growth", "adapter": "claude_code"},
            {"handle": "risk", "adapter": "claude_code"},
        ]
        rows = self.project(agents=agents, members=[{"handle": "growth", "kind": "slim"}])
        agent_rows = [r for r in rows if r.id.startswith("agent:")]
        assert [r.id for r in agent_rows] == ["agent:growth"]
        assert custody.lens_of_item(agent_rows[0], NOW) == "in_flight"

    def test_a_live_episode_reads_as_a_decision_and_drops_the_urn(self):
        episodes = [
            {
                "short_id": "e4f1",
                "topic": "urn:concept:mycelium:atlas-migration",
                "outcome": "open",
                "subkind": None,
                "participants": ["growth", "risk"],
                "message_count": 6,
                "updated_at": "2026-08-22T11:00:00Z",
            }
        ]
        row = next(r for r in self.project(episodes=episodes) if r.id.startswith("episode:"))
        assert row.kind == "decision"
        assert row.title.startswith("atlas migration: negotiating")


URN = "urn:ioc:mycelium:episode:atlas:e4f1a2"

EPISODE = {
    "short_id": "e4f1a2",
    "episode": URN,
    "topic": "urn:concept:mycelium:atlas",
    "outcome": "converged",
    "subkind": "converged",
    "participants": ["growth", "risk"],
    "message_count": 7,
    "updated_at": "2026-08-22T10:00:00Z",
}


def task(**extra) -> dict:
    return {
        "key": "work/cutover",
        "value": "run the cutover",
        "updated_at": "2026-08-22T10:00:00Z",
        "updated_by": "aligner",
        "episode": URN,
        "meta": {"kind": "action", "status": "open", **extra},
    }


class TestUnitOfWork:
    """A task is one row, and it is a thread.

    The GUI runs the same six cases over its own projection; neither surface may
    start drawing a task and its thread as two rows without the other.
    """

    def project(self, episodes: list[dict], memories: list[dict]) -> list[LiveItem]:
        return project_items(episodes=episodes, memories=memories, agents=[], members=[], now=NOW)

    def test_folds_a_bound_episode_into_the_row_instead_of_a_second_one(self):
        rows = self.project([EPISODE], [task()])
        assert [r.id for r in rows] == ["memory:work/cutover"]
        assert rows[0].fields["episode"] == URN
        assert rows[0].fields["thread"] == "e4f1a2"
        assert rows[0].fields["thread_state"] == "converged"
        assert rows[0].fields["participants"] == ["growth", "risk"]
        assert rows[0].fields["rounds"] == 7

    def test_a_closing_thread_leaves_the_unit_s_own_axes_alone(self):
        # The container outlives the negotiation. A converged episode is a fact
        # about the conversation, not a claim that the work is done or that
        # anyone is holding it.
        held = {
            "custody": "held",
            "owner": "@growth",
            "claimed_at": "2026-08-22T11:55:00Z",
            "ttl_minutes": 30,
        }
        row = self.project([EPISODE], [task(**held)])[0]
        assert row.status == "open"
        assert row.owner == "growth"
        assert custody.custody_of(row, NOW) == "held"

    def test_an_orphaned_episode_keeps_a_row_of_its_own(self):
        # A recorded negotiation nobody compiled into work is still something
        # the room did, so it is surfaced rather than hidden or deleted.
        rows = self.project([EPISODE], [])
        assert [r.id for r in rows] == ["episode:e4f1a2"]
        assert rows[0].fields["episode"] == URN

    def test_every_row_compiled_out_of_one_negotiation_carries_it(self):
        second = {**task(), "key": "work/soak"}
        rows = self.project([EPISODE], [task(), second])
        assert [r.id for r in rows] == ["memory:work/cutover", "memory:work/soak"]
        assert all(r.fields["thread_state"] == "converged" for r in rows)

    def test_a_unit_no_thread_has_run_in_says_nothing_it_does_not_know(self):
        # The inversion: a task is created board-first and worked with no episode
        # ever opened. It carries its binding and claims no thread state.
        row = self.project([], [task()])[0]
        assert row.fields["episode"] == URN
        assert row.fields["thread"] == "e4f1a2"
        assert "thread_state" not in row.fields
        assert "rounds" not in row.fields

    def test_a_row_with_no_binding_is_left_alone(self):
        row = self.project([], [{**task(), "episode": None}])[0]
        assert "episode" not in row.fields
        assert "thread" not in row.fields


class TestSchema:
    def test_reads_a_rooms_own_repeated_vocabulary_as_a_select(self):
        schema = infer_schema(
            [item("a", severity="sev2"), item("b", severity="sev2"), item("c", severity="sev1")]
        )
        severity = next(f for f in schema if f.name == "severity")
        assert severity.type == "select"
        assert severity.options == [("sev2", 2), ("sev1", 1)]

    def test_keeps_one_off_prose_as_text(self):
        schema = infer_schema(
            [item("a", note="the aligner stalled"), item("b", note="cache needs a pass")]
        )
        assert next(f for f in schema if f.name == "note").type == "text"

    def test_offers_a_defined_vocabulary_whole_and_in_order(self):
        schema = infer_schema([item("a", status="open")])
        status = next(f for f in schema if f.name == "status")
        assert [value for value, _ in status.options] == CONTRACT["statuses"]
        assert dict(status.options)["dismissed"] == 0

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [
            ("owner", "@julia", "handle"),
            ("updated", "2026-08-22T10:00:00Z", "date"),
            ("rounds", 3, "number"),
            ("tags", ["auth"], "tags"),
            ("live", True, "checkbox"),
        ],
    )
    def test_types_fields_apart(self, name, value, expected):
        schema = infer_schema([item("a", **{name: value}), item("b", **{name: value})])
        assert next(f for f in schema if f.name == name).type == expected

    def test_only_bounded_fields_can_become_columns(self):
        schema = infer_schema(
            [
                item("a", status="open", headline="one"),
                item("b", status="in_review", headline="two"),
            ]
        )
        assert [f.name for f in groupable_fields(schema)] == ["status"]


class TestLogContract:
    """Day and week conventions the GUI's log carries its own copy of."""

    def test_calendar_conventions_match_the_contract(self):
        log = CONTRACT["log"]
        assert log["week_starts_on"] == activity.WEEK_STARTS_ON
        assert log["daily_goal"] == activity.DAILY_GOAL
        assert log["heat_thresholds"] == activity.HEAT_THRESHOLDS

    def test_heat_steps_at_the_contracted_bounds(self):
        upper = CONTRACT["log"]["heat_thresholds"]
        for level, bound in enumerate(upper):
            assert activity.heat_level(bound) == level
        assert activity.heat_level(upper[-1] + 1) == len(upper)

    def test_weeks_start_on_monday(self):
        assert activity.week_start(date(2026, 8, 22)) == date(2026, 8, 17)
        assert activity.week_start(date(2026, 8, 17)) == date(2026, 8, 17)


def instant(raw: str) -> datetime:
    """Parse-or-fail, so a test never silently builds an event with no time."""
    parsed = activity.parse_instant(raw)
    assert parsed is not None
    return parsed


class TestActivity:
    def project(self, **over):
        kwargs = {
            "messages": [],
            "memories": [],
            "episodes": [],
            "agent_handles": ["growth"],
        }
        kwargs.update(over)
        return activity.project_activity(**kwargs)

    def test_an_instant_lands_on_a_different_day_depending_on_the_clock(self):
        at = activity.parse_instant("2026-08-22T03:30:00Z")
        assert at is not None
        assert activity.day_of(at, activity.zone("UTC")) == date(2026, 8, 22)
        assert activity.day_of(at, activity.zone("America/Los_Angeles")) == date(2026, 8, 21)
        assert activity.day_of(at, activity.zone("Asia/Tokyo")) == date(2026, 8, 22)

    def test_an_unknown_zone_falls_back_rather_than_failing(self):
        assert activity.zone("Mars/Olympus").key == "UTC"

    def test_chat_is_attributed_and_agents_are_told_from_people(self):
        events = self.project(
            messages=[
                {
                    "id": "1",
                    "message_type": "broadcast",
                    "sender_handle": "growth",
                    "content": "dual-write is live",
                    "created_at": "2026-08-22T10:00:00Z",
                },
                {
                    "id": "2",
                    "message_type": "broadcast",
                    "sender_handle": "julia",
                    "content": "nice",
                    "created_at": "2026-08-22T10:05:00Z",
                },
                {
                    "id": "3",
                    "message_type": "broadcast",
                    "sender_handle": "aligner",
                    "content": "standing offer",
                    "created_at": "2026-08-22T10:06:00Z",
                },
            ]
        )
        assert [(e.actor, e.actor_kind) for e in events] == [
            ("aligner", "engine"),
            ("julia", "human"),
            ("growth", "agent"),
        ]

    def test_a_coordination_payload_is_read_by_type_not_printed(self):
        events = self.project(
            messages=[
                {
                    "id": "1",
                    "message_type": "coordination_tick",
                    "sender_handle": "aligner",
                    "content": json.dumps(
                        {"payload": {"round": 4, "participant_id": "risk", "action": "accept"}}
                    ),
                    "created_at": "2026-08-22T10:00:00Z",
                }
            ]
        )
        assert events[0].verb == "negotiated"
        assert events[0].title == "round 4 · @risk accept"
        assert "{" not in events[0].title

    def test_the_same_work_is_not_logged_from_both_the_wire_and_the_store(self):
        events = self.project(
            messages=[
                {
                    "id": "1",
                    "message_type": "memory_changed",
                    "sender_handle": "growth",
                    "content": "{}",
                    "created_at": "2026-08-22T10:00:00Z",
                },
                {
                    "id": "2",
                    "message_type": "coordination_consensus",
                    "sender_handle": "aligner",
                    "content": "{}",
                    "created_at": "2026-08-22T10:01:00Z",
                },
            ],
            memories=[
                {
                    "key": "decisions/cutover",
                    "value": "phased",
                    "version": 2,
                    "created_by": "aligner",
                    "updated_by": "growth",
                    "updated_at": "2026-08-22T10:00:00Z",
                },
            ],
        )
        assert len(events) == 1
        assert (events[0].actor, events[0].verb) == ("growth", "revised")

    def test_anything_unattributed_or_untimed_is_dropped(self):
        events = self.project(
            messages=[
                {
                    "id": "1",
                    "message_type": "broadcast",
                    "content": "who said this?",
                    "created_at": "2026-08-22T10:00:00Z",
                },
                {
                    "id": "2",
                    "message_type": "broadcast",
                    "sender_handle": "julia",
                    "content": "when?",
                },
            ]
        )
        assert events == []

    def test_a_streak_tolerates_a_day_that_has_not_started(self):
        tz = activity.zone("UTC")
        events = [
            activity.ActivityEvent(
                "a",
                instant("2026-08-22T10:00:00Z"),
                "julia",
                "human",
                "posted",
                "x",
                "t",
            ),
            activity.ActivityEvent(
                "b",
                instant("2026-08-21T10:00:00Z"),
                "julia",
                "human",
                "posted",
                "x",
                "t",
            ),
        ]
        days = activity.by_day(events, tz)
        assert activity.streaks(days, date(2026, 8, 22)) == (2, 2)
        assert activity.streaks(days, date(2026, 8, 23))[0] == 2
        assert activity.streaks(days, date(2026, 8, 24))[0] == 0

    def test_a_digest_lanes_actors_busiest_first(self):
        tz = activity.zone("UTC")
        events = [
            activity.ActivityEvent(
                str(i),
                instant("2026-08-22T10:00:00Z"),
                actor,
                "human",
                "posted",
                "x",
                "t",
            )
            for i, actor in enumerate(["julia", "julia", "growth"])
        ]
        summary = activity.digest(activity.by_day(events, tz), date(2026, 8, 22), date(2026, 8, 22))
        assert [(actor, len(rows)) for actor, _, rows in summary.by_actor] == [
            ("julia", 2),
            ("growth", 1),
        ]
        assert summary.active_days == 1
        assert summary.by_verb == [("posted", 3)]


def status_payload(*entries, rows=None) -> dict:
    """A hub /status response: refs keyed by row id, the shape the route returns."""
    return {
        "field": "upstream",
        "refs": list(entries),
        "rows": rows or {},
    }


def answer(ref: str, state: str | None, label: str | None = None, **extra) -> dict:
    base = {"ref": ref, "state": state, "label": label, "url": None, "error": None}
    return {**base, "freshness": "fresh", **extra}


class TestUpstream:
    def test_an_answer_lands_on_the_row_that_mentioned_it(self):
        rows = [item("memory:work/cutover", status="open")]
        attach_upstream(
            rows,
            status_payload(
                answer("github:pull_request:o/r#1", "blocked", "changes requested"),
                rows={"memory:work/cutover": ["github:pull_request:o/r#1"]},
            ),
        )
        assert rows[0].get("upstream") == "blocked"
        assert rows[0].get("upstream_label") == "changes requested"

    def test_a_row_with_two_references_shows_the_worse_one_and_says_there_were_more(self):
        rows = [item("memory:work/cutover")]
        attach_upstream(
            rows,
            status_payload(
                answer("a", "ok", "approved"),
                answer("b", "failed", "CI failing"),
                rows={"memory:work/cutover": ["a", "b"]},
            ),
        )
        # A board says what needs a person, so the failing one wins; the count
        # keeps the summary from standing in for the whole.
        assert rows[0].get("upstream") == "failed"
        assert rows[0].get("upstream_count") == 2

    def test_a_row_nothing_was_found_for_carries_no_field_at_all(self):
        rows = [item("memory:work/other")]
        attach_upstream(
            rows, status_payload(answer("a", "ok"), rows={"memory:work/cutover": ["a"]})
        )
        # Absent, not empty: a view can tell "nothing upstream" from "unknown".
        assert "upstream" not in rows[0].fields

    def test_an_errored_answer_shows_the_reason_rather_than_an_empty_label(self):
        rows = [item("memory:work/cutover")]
        attach_upstream(
            rows,
            status_payload(
                answer("a", "unknown", None, error="not visible to this token"),
                rows={"memory:work/cutover": ["a"]},
            ),
        )
        assert rows[0].get("upstream_label") == "not visible to this token"

    def test_no_hub_answer_leaves_every_row_untouched(self):
        rows = [item("memory:work/cutover", status="open")]
        attach_upstream(rows, None)
        assert rows[0].fields == {"status": "open"}

    def test_a_row_whose_answer_has_not_come_back_is_pending_not_unknown(self):
        rows = [item("memory:work/cutover")]
        payload = status_payload(
            answer("a", None, freshness="missing"), rows={"memory:work/cutover": ["a"]}
        )
        attach_upstream(rows, {**payload, "refreshing": True})
        # `unknown` is a provider saying it could not place what it found; this
        # is nobody having answered yet. Grouping by upstream must not collect a
        # bucket of rows that were merely early.
        assert "upstream" not in rows[0].fields
        assert rows[0].get("upstream_pending") is True

    def test_a_row_shows_what_is_known_when_one_of_two_answers_has_not_landed(self):
        rows = [item("memory:work/cutover")]
        attach_upstream(
            rows,
            status_payload(
                answer("a", None, freshness="missing"),
                answer("b", "blocked", "changes requested"),
                rows={"memory:work/cutover": ["a", "b"]},
            ),
        )
        assert rows[0].get("upstream") == "blocked"

    def test_a_stale_value_is_kept_and_marked_rather_than_hidden(self):
        rows = [item("memory:work/cutover")]
        attach_upstream(
            rows,
            status_payload(
                answer("a", "ok", "approved", freshness="stale", age_seconds=5400),
                rows={"memory:work/cutover": ["a"]},
            ),
        )
        # The truth as far as anyone knows, with a refresh behind it. Taking the
        # value away would tell the reader less, not more.
        assert rows[0].get("upstream") == "ok"
        assert rows[0].get("upstream_freshness") == "stale"
        assert rows[0].get("upstream_age") == "1h ago"

    def test_upstream_is_a_select_the_board_can_group_by(self):
        rows = [item("a", upstream="ok"), item("b", upstream="failed")]
        found = next(f for f in infer_schema(rows) if f.name == "upstream")
        assert found.type == "select"
        assert {name for name, _ in found.options} <= set(UPSTREAM_STATES)
        assert "upstream" in [f.name for f in groupable_fields(infer_schema(rows))]


class TestTheTableSurvivesRoomContent:
    def test_a_title_carrying_square_brackets_renders_rather_than_raising(self):
        """Room content is not Rich markup.

        `add_row` parses a plain string as markup, so a title like
        "retire the [/legacy] store" raised MarkupError and took the whole
        `--view table` down with it.
        """
        from rich.console import Console

        from mycelium.commands.board import _table

        rows = [
            LiveItem(
                id="memory:x",
                title="retire the [/legacy] store",
                source=ItemSource("memory", "x"),
                fields={"status": "open", "kind": "action", "branch": "feat/[wip]"},
            )
        ]
        console = Console(width=90, record=True)
        console.print(_table(rows, rows))
        output = console.export_text()
        assert "[/legacy]" in output
        assert "feat/[wip]" in output


class TestHubHealthSaysWhatActuallyHappened:
    """Reachability used to be inferred from one endpoint, so an authenticated
    hub refusing a request read as "hub unreachable", and a board drawn with two
    of its sources missing read as a quiet room."""

    def test_a_hub_that_is_not_there_is_reported_as_unreachable(self):
        from mycelium.commands.board import HubHealth

        health = HubHealth(failed={"plan": "ConnectError", "memory": "ConnectError"})
        assert not health.reachable
        assert "unreachable" in (health.note or "")

    def test_a_hub_that_refuses_is_not_reported_as_missing(self):
        from mycelium.commands.board import HubHealth

        health = HubHealth(
            failed={"plan": "HTTP 401", "memory": "HTTP 401"}, answered=["plan", "memory"]
        )
        note = health.note or ""
        assert "refused" in note
        assert "401" in note
        # The reader's problem is a credential; do not send them to their network.
        assert "unreachable" not in note

    def test_a_partly_answered_board_says_it_is_incomplete(self):
        from mycelium.commands.board import HubHealth

        health = HubHealth(
            ok=["plan", "agents"],
            answered=["plan", "agents", "memory"],
            failed={"memory": "HTTP 500"},
        )
        # It still draws, because two of three sources is worth seeing, but a
        # sparse board must never be mistaken for a quiet room.
        assert health.reachable
        assert "Incomplete" in (health.note or "")
        assert "memory" in (health.note or "")

    def test_a_healthy_read_says_nothing_at_all(self):
        from mycelium.commands.board import HubHealth

        assert HubHealth(ok=["plan"], answered=["plan"]).note is None
