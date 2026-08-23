# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Custody: the board's claims, held as leases rather than as facts.

The property under test throughout is the one an ephemeral actor forces: nobody
gets to announce that they died, so a claim has to stop being true on its own.
A board where every agent went quiet an hour ago must read empty.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mycelium.board import custody
from mycelium.board.model import ItemSource, LiveItem
from mycelium.board.projection import project_items

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)["custody"]

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def row(source: str = "memory", label: str = "work/auth-spike", **fields) -> LiveItem:
    return LiveItem(
        id=f"{source}:{label}", title=label, source=ItemSource(source, label), fields=fields
    )


def held(minutes_ago: float, ttl: int = 30, owner: str = "@growth", **extra) -> LiveItem:
    return row(custody="held", owner=owner, claimed_at=ago(minutes_ago), ttl_minutes=ttl, **extra)


class TestVocabularyContract:
    """The GUI carries its own copy of every word here."""

    def test_states_match_the_contract(self):
        assert CONTRACT["states"] == custody.STATES
        assert CONTRACT["stored_states"] == custody.STORED_STATES
        assert CONTRACT["derived_states"] == custody.DERIVED_STATES
        assert CONTRACT["freshness"] == custody.FRESHNESS

    def test_derived_states_are_never_writable(self):
        """The two halves of the enum have to stay disjoint and exhaustive: a
        state that is both stored and derived would let a writer freeze a row in
        the one state the clock is supposed to own."""
        assert set(custody.STORED_STATES) & set(custody.DERIVED_STATES) == set()
        assert set(custody.STORED_STATES) | set(custody.DERIVED_STATES) == set(custody.STATES)

    def test_every_state_maps_to_a_lens(self):
        assert CONTRACT["lens_of_custody"] == custody.LENS_OF_CUSTODY
        assert set(custody.LENS_OF_CUSTODY) == set(custody.STATES)

    def test_thresholds_and_fields_match_the_contract(self):
        assert CONTRACT["stale_after"] == custody.STALE_AFTER
        assert CONTRACT["default_ttl_minutes"] == custody.DEFAULT_TTL_MINUTES
        assert CONTRACT["companion_fields"] == custody.COMPANION_FIELDS
        assert CONTRACT["runtime_author"] == custody.RUNTIME_AUTHOR
        assert CONTRACT["leasable_namespaces"] == custody.LEASABLE_NAMESPACES
        assert CONTRACT["blocked_field"] == custody.BLOCKED_FIELD
        assert CONTRACT["refusals"] == custody.REFUSALS

    def test_a_claim_writes_exactly_the_contracted_fields(self):
        """The patch is asserted against what it actually produces, not against a
        second copy of the list — a companion field nobody writes is a column the
        GUI would render forever empty."""
        patch = custody.claim_patch("growth", NOW)
        written = set(patch) - {"owner", custody.FIELD}
        assert written <= set(custody.COMPANION_FIELDS)
        assert patch[custody.FIELD] in custody.STORED_STATES


class TestFreshness:
    """The same shape the upstream half already ships, pointed at claimed_at."""

    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [
            (0, "fresh"),
            (10, "fresh"),
            (14.9, "fresh"),
            (15, "stale"),
            (29, "stale"),
            (31, "expired"),
        ],
    )
    def test_a_lease_ages_fresh_then_stale_then_expired(self, minutes, expected):
        assert custody.freshness(ago(minutes), 30, NOW) == expected

    def test_a_row_with_no_ttl_has_no_freshness(self):
        """A row nobody took for a window has nothing to report rather than a
        zero — an answer of "fresh" would be a claim about a lease never taken."""
        assert custody.freshness(ago(500), None, NOW) is None
        assert custody.elapsed_fraction(ago(500), None, NOW) is None

    def test_minutes_left_counts_down_and_floors_at_zero(self):
        assert custody.remaining_minutes(held(10), NOW) == 20
        assert custody.remaining_minutes(held(90), NOW) == 0
        assert custody.remaining_minutes(row(status="open"), NOW) is None


class TestCustodyState:
    def test_a_fresh_claim_is_held(self):
        assert custody.custody_of(held(5), NOW) == "held"

    def test_a_stale_claim_is_still_held(self):
        """Stale is a renewal being due, not a lease being over. The holder is
        past half its TTL and has not said anything — that is what a renewal is
        for, and taking the row away at that point would thrash."""
        assert custody.custody_of(held(20), NOW) == "held"

    def test_a_claim_nobody_renewed_expires_with_nothing_written(self):
        """The row on disk still says `held`. Time is what changed."""
        item = held(90)
        assert item.fields[custody.FIELD] == "held"
        assert custody.custody_of(item, NOW) == "expired"

    def test_held_by_nobody_is_not_held(self):
        assert custody.custody_of(row(custody="held", claimed_at=ago(1)), NOW) == "unclaimed"

    def test_a_claim_with_no_stamp_at_all_cannot_be_shown_to_be_alive(self):
        """A lease has to be datable to be evidence. With neither a claim stamp
        nor a row stamp there is nothing to age it against, so it reads expired
        rather than being trusted forever."""
        assert (
            custody.custody_of(row(custody="held", owner="@growth", ttl_minutes=30), NOW)
            == "expired"
        )

    def test_a_claim_with_no_window_is_not_a_lease(self):
        """`held` with no TTL says "mine, indefinitely" — the exact assertion an
        actor that can vanish is not entitled to make."""
        item = row(custody="held", owner="@growth", claimed_at=ago(1))
        assert custody.custody_of(item, NOW) == "expired"

    def test_a_hand_written_claim_dates_from_the_file(self):
        """`claimed_at` falls back to when the row last moved: someone typing
        `owner:` into frontmatter has still made a claim, and dating it from the
        file beats treating it as claimed just now."""
        item = row(custody="held", owner="@growth", ttl_minutes=30, updated=ago(90))
        assert custody.custody_of(item, NOW) == "expired"

    def test_a_row_with_no_custody_field_has_no_custody_axis(self):
        """`None` is not a state: a decision that has been made is not unclaimed,
        it is simply not the kind of thing anybody holds."""
        assert custody.custody_of(row(status="resolved"), NOW) is None

    def test_an_unknown_custody_value_is_not_a_state(self):
        assert custody.custody_of(row(custody="in_progress"), NOW) is None


class TestLens:
    def test_a_held_row_is_in_flight_and_drains_back_to_needs_you(self):
        assert custody.lens_of_item(held(5), NOW) == "in_flight"
        assert custody.lens_of_item(held(90), NOW) == "needs_you"

    def test_released_and_unclaimed_rows_are_both_in_the_pool(self):
        assert custody.lens_of_item(row(custody="released"), NOW) == "needs_you"
        assert custody.lens_of_item(row(custody="unclaimed"), NOW) == "needs_you"

    def test_a_row_with_no_custody_falls_back_to_its_stage(self):
        assert custody.lens_of_item(row(status="in_review"), NOW) == "in_flight"
        assert custody.lens_of_item(row(status="resolved"), NOW) == "resolved"

    def test_blocked_beats_a_live_claim(self):
        """Whoever nominally holds it, a row waiting on something needs a person."""
        assert custody.lens_of_item(held(5, blocked_by=["#502"]), NOW) == "needs_you"


class TestBlockedIsDerived:
    def test_a_row_is_blocked_because_it_names_a_blocker(self):
        assert custody.is_blocked(row(blocked_by=["#502"]))
        assert custody.is_blocked(row(blocked_by="#502"))
        assert not custody.is_blocked(row(blocked_by=[]))
        assert not custody.is_blocked(row())

    def test_the_word_blocked_is_not_a_status_anyone_can_store(self):
        from mycelium.board.model import STATUSES

        assert "blocked" not in STATUSES
        # Writing it anyway doesn't make the row blocked: only a named blocker does.
        assert not custody.is_blocked(row(status="blocked"))


class TestRefusals:
    @pytest.mark.parametrize("kind", ["episode", "agent"])
    def test_rows_that_cannot_hold_a_lease_say_why(self, kind):
        reason = custody.custody_refusal(row(kind, "t3"))
        assert reason == custody.REFUSALS[kind]

    def test_an_episode_refuses_a_claim_with_its_own_reason(self):
        reason = custody.custody_refusal(row("episode", "e4f1"))
        assert reason is not None
        assert "nothing to write a lease onto" in reason

    def test_a_work_memory_takes_a_lease(self):
        assert custody.custody_refusal(row("memory", "work/auth", namespace="work")) is None

    def test_a_memory_in_another_namespace_does_not(self):
        assert custody.custody_refusal(row("memory", "status/ci", namespace="status")) is not None


class TestNotes:
    def test_a_release_note_is_signed_by_whoever_released_it(self):
        item = row(
            custody="released",
            custody_note="handing to whoever picks it up",
            custody_note_by="growth",
        )
        assert custody.note_of(item, NOW) == ("handing to whoever picks it up", "growth")

    def test_an_expired_lease_leaves_a_note_the_runtime_signed(self):
        signed = custody.note_of(held(90), NOW)
        assert signed is not None
        note, author = signed
        assert author == custody.RUNTIME_AUTHOR
        assert "stopped renewing" in note

    def test_a_reader_can_tell_a_handoff_from_an_abandonment(self):
        """Both leave an unclaimed row with history — the byline is the difference."""
        handed = row(custody="released", custody_note="done with my half", custody_note_by="growth")
        abandoned = held(90)
        by_hand = custody.note_of(handed, NOW)
        by_clock = custody.note_of(abandoned, NOW)
        assert by_hand is not None
        assert by_clock is not None
        assert by_hand[1] != by_clock[1]
        assert custody.lens_of_item(handed, NOW) == custody.lens_of_item(abandoned, NOW)

    def test_a_claim_clears_a_previous_holders_note(self):
        patch = custody.claim_patch("risk", NOW)
        assert patch["custody_note"] is None
        assert patch["custody_note_by"] is None


class TestPatches:
    def test_a_claim_stamps_a_holder_a_time_and_a_window(self):
        patch = custody.claim_patch("growth", NOW, ttl_minutes=45)
        assert patch == {
            "custody": "held",
            "owner": "@growth",
            "claimed_at": NOW.isoformat(),
            "ttl_minutes": 45,
            "custody_note": None,
            "custody_note_by": None,
        }

    def test_a_release_clears_the_holder_and_leaves_a_note(self):
        patch = custody.release_patch("@growth", NOW, note="blocked on infra")
        assert patch["custody"] == "released"
        assert patch["owner"] is None
        assert patch["claimed_at"] is None
        assert patch["custody_note"] == "blocked on infra"
        assert patch["custody_note_by"] == "growth"

    def test_a_renewal_changes_nothing_but_the_stamp(self):
        """Renewal is a heartbeat, not news: it re-dates the same lease and
        touches no other field, which is what lets it be quiet."""
        assert custody.renew_patch(NOW) == {"claimed_at": NOW.isoformat()}


class TestProjection:
    """What the room's own state looks like once custody is the axis."""

    def project(self, **over):
        kwargs = {"episodes": [], "memories": [], "agents": [], "members": []}
        kwargs.update(over)
        return project_items(now=NOW, **kwargs)

    def memory(self, key: str, **value):
        return {
            "key": key,
            "value": {"text": "body", **value},
            "created_by": "julia",
            "updated_by": "julia",
            "updated_at": ago(5),
        }

    def test_a_work_memory_starts_unclaimed_rather_than_owned_by_its_writer(self):
        """Reading `owner` off `updated_by` gave every memory in the room a
        holder — the confident lie this axis exists to stop."""
        rows = self.project(memories=[self.memory("work/auth-spike")])
        assert rows[0].fields[custody.FIELD] == "unclaimed"
        assert rows[0].owner is None
        assert rows[0].fields["writer"] == "@julia"

    def test_a_claim_in_frontmatter_projects_as_a_live_lease(self):
        memories = [
            self.memory(
                "work/auth-spike",
                custody="held",
                owner="@growth",
                claimed_at=ago(3),
                ttl_minutes=30,
            )
        ]
        row_ = self.project(memories=memories)[0]
        assert custody.custody_of(row_, NOW) == "held"
        assert custody.lens_of_item(row_, NOW) == "in_flight"

    def test_only_work_memories_carry_a_custody_axis(self):
        rows = self.project(memories=[self.memory("status/ci"), self.memory("work/auth")])
        by_key = {r.id: r for r in rows}
        assert custody.FIELD not in by_key["memory:status/ci"].fields
        assert custody.FIELD in by_key["memory:work/auth"].fields

    def test_a_resident_agents_row_is_dated_from_its_last_poll(self):
        agents = [{"handle": "growth", "adapter": "claude_code"}]
        members = [{"handle": "growth", "kind": "lease", "last_seen": ago(2)}]
        rows = self.project(agents=agents, members=members)
        assert custody.custody_of(rows[0], NOW) == "held"
        assert rows[0].fields["claimed_at"] == ago(2)

    def test_a_board_whose_agents_all_died_an_hour_ago_reads_empty(self):
        """The test the whole model exists to pass."""
        agents = [
            {"handle": "growth", "adapter": "claude_code"},
            {"handle": "risk", "adapter": "cursor"},
        ]
        members = [
            {"handle": "growth", "kind": "lease", "last_seen": ago(60)},
            {"handle": "risk", "kind": "lease", "last_seen": ago(75)},
        ]
        rows = self.project(agents=agents, members=members)
        assert rows == []

    def test_work_a_dead_agent_was_holding_returns_to_the_pool(self):
        """Nobody touched the row. It drained."""
        memories = [
            self.memory(
                "work/auth-spike",
                custody="held",
                owner="@growth",
                claimed_at=ago(90),
                ttl_minutes=30,
            )
        ]
        row_ = self.project(memories=memories)[0]
        assert custody.custody_of(row_, NOW) == "expired"
        assert custody.lens_of_item(row_, NOW) == "needs_you"

    def test_a_rejected_episode_wants_a_person_without_claiming_to_be_blocked(self):
        episodes = [
            {
                "short_id": "e4f1",
                "topic": "urn:concept:mycelium:atlas",
                "subkind": "rejected",
                "participants": ["growth", "risk"],
                "updated_at": ago(10),
            }
        ]
        row_ = self.project(episodes=episodes)[0]
        assert row_.status == "open"
        assert row_.kind == "blocked"
        assert custody.lens_of_item(row_, NOW) == "needs_you"
