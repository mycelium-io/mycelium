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

from mycelium.board import activity, model
from mycelium.board.model import ItemSource, LiveItem, lens_of
from mycelium.board.projection import demo_items, project_items
from mycelium.board.schema import groupable_fields, infer_schema

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


class TestProjection:
    plan = {
        "room": "atlas",
        "files": [{"slug": "tasks", "updated_at": "2026-08-20T10:00:00Z"}],
        "tasks": [
            {
                "id": "t1",
                "slug": "tasks",
                "line": 2,
                "text": "flip reads behind a flag @growth",
                "done": False,
            },
            {
                "id": "t2",
                "slug": "tasks",
                "line": 3,
                "text": "retire the legacy store @risk",
                "done": True,
            },
        ],
    }

    def project(
        self,
        *,
        episodes: list[dict] | None = None,
        memories: list[dict] | None = None,
        agents: list[dict] | None = None,
        members: list[dict] | None = None,
    ) -> list[LiveItem]:
        return project_items(
            plan=self.plan,
            episodes=episodes or [],
            memories=memories or [],
            agents=agents or [],
            members=members or [],
            now=NOW,
        )

    def test_lifts_a_plan_task_handle_into_an_owner(self):
        rows = self.project()
        assert rows[0].owner == "growth"
        assert rows[0].title == "flip reads behind a flag"
        assert rows[0].status == "in_progress"

    def test_a_done_task_resolves(self):
        assert self.project()[1].status == "resolved"

    def test_every_row_carries_its_provenance(self):
        assert self.project()[0].source.label == "plan/tasks.md:2"

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
        assert agent_rows[0].lens == "in_flight"

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

    def test_the_demo_layer_stamps_every_row_it_adds(self):
        assert all(row.demo for row in demo_items(NOW))
        assert not any(row.demo for row in self.project())


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
        assert dict(status.options)["claimed"] == 0

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
            [item("a", status="open", headline="one"), item("b", status="blocked", headline="two")]
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
            "plan": None,
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

    def test_a_finished_task_is_credited_to_its_owner(self):
        plan = {
            "files": [
                {
                    "slug": "tasks",
                    "updated_at": "2026-08-21T09:00:00Z",
                    "tasks": [
                        {"id": "t1", "text": "dual-write to the new store @growth", "done": True},
                        {"id": "t2", "text": "flip reads @risk", "done": False},
                    ],
                }
            ]
        }
        events = self.project(plan=plan)
        assert [(e.actor, e.verb, e.title) for e in events] == [
            ("growth", "completed", "dual-write to the new store")
        ]

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
