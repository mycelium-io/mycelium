# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ends a hold with no timer, and what flags a quiet one (#1136).

A row given to someone is held until something real ends it: the holder's pane
closes, it leaves the room, or the hub has seen nothing of it for a long time.
A quiet row whose holder is around is flagged once, never released.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest

from app.schemas import MachineAgentRead, MachineReportRead, MachineWorkspaceRead, RunnerHello
from app.services import assignments, hold_sweep
from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
from app.services.runners import RunnerRegistry

ROOM = "holds"
KEY = "work/turn-on-apple-pay"


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The notices the sweep raises and the lines it posts, captured."""
    from app.services.room_channels import manager

    raised: list[dict[str, Any]] = []

    async def capture(room: str, **notice: Any) -> None:
        raised.append(notice)

    monkeypatch.setattr(manager, "raise_notice", capture)
    return raised


def _row(**meta: Any) -> None:
    write_memory_file(
        get_room_dir(ROOM),
        KEY,
        "# Turn on Apple Pay",
        created_by="lead",
        extra_meta={"assignee": "coder", "episode": "urn:ioc:mycelium:episode:holds:t1", **meta},
    )


def _meta() -> dict:
    found = read_memory_file(get_room_dir(ROOM), KEY)
    assert found is not None
    return found[0]


def _sweep(hours: float) -> list[tuple[str, str, str]]:
    return asyncio.run(hold_sweep.sweep(datetime.now(UTC) + timedelta(hours=hours)))


@pytest.fixture(autouse=True)
def _fresh_sweep_counts() -> None:
    hold_sweep._closed_sweeps.clear()


def test_a_closed_pane_ends_the_hold_on_the_second_sweep_and_says_so(monkeypatch, notices):
    _row()
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "closed")
    # An agent restarting can show only its old, closed pane for one sweep.
    assert _sweep(0) == []
    assert _sweep(0) == [(ROOM, KEY, "released")]
    meta = _meta()
    assert assignments.state_of(meta, datetime.now(UTC)) == "released"
    assert meta["assignment_note"] == "@coder's herdr pane closed"
    assert meta["assignment_note_by"] == assignments.RUNTIME_AUTHOR
    (notice,) = notices
    assert (notice["subkind"], notice["by"]) == ("released", "runtime")
    assert notice["why"] == "@coder's herdr pane closed"


def test_a_pane_that_comes_back_is_not_released(monkeypatch, notices):
    _row()
    seen = iter(["closed", "present", "closed"])
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: next(seen))
    assert [_sweep(0) for _ in range(3)] == [[], [], []]
    assert assignments.state_of(_meta(), datetime.now(UTC)) == "held"


def test_an_agent_holding_two_rows_gets_the_same_grace(monkeypatch, notices):
    # The closed count goes up once per sweep, not once per row it holds.
    other = "work/turn-on-google-pay"
    _row()
    write_memory_file(
        get_room_dir(ROOM),
        other,
        "# Turn on Google Pay",
        created_by="lead",
        extra_meta={"assignee": "coder", "episode": "urn:ioc:mycelium:episode:holds:t2"},
    )
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "closed")
    assert _sweep(0) == []
    assert sorted(_sweep(0)) == [(ROOM, KEY, "released"), (ROOM, other, "released")]


def test_removing_an_agent_releases_what_it_held(notices):
    from app.routes.memory import delete_memory

    _row()
    write_memory_file(get_room_dir(ROOM), "agents/coder", "handle: coder", created_by="lead")
    write_memory_file(get_room_dir(ROOM), "agents/coder/notes", "notes", created_by="lead")
    # Its notes going is not the agent leaving.
    asyncio.run(delete_memory(ROOM, "agents/coder/notes"))
    assert assignments.state_of(_meta(), datetime.now(UTC)) == "held"
    asyncio.run(delete_memory(ROOM, "agents/coder"))
    meta = _meta()
    assert assignments.state_of(meta, datetime.now(UTC)) == "released"
    assert meta["assignment_note"] == "@coder was removed from the room"
    (notice,) = notices
    assert (notice["subkind"], notice["why"]) == ("released", "@coder was removed from the room")


def test_a_holder_with_no_manifest_or_user_record_keeps_the_row(monkeypatch, notices):
    # A person who never set up a user record looks like this, so it is unseen,
    # not gone: the row stays held until the long fallback.
    from app.services.room_channels import manager

    _row(assignee="operator", hold_flagged_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(manager, "herdr_status", lambda _r, _h: None)
    monkeypatch.setattr(manager, "members", lambda _r: [])
    assert hold_sweep.signal_of(ROOM, "operator") == "unseen"
    assert _sweep(0) == []
    assert _sweep(1) == []
    assert assignments.state_of(_meta(), datetime.now(UTC)) == "held"
    assert notices == []


def test_a_holder_the_hub_can_see_is_never_expired_for_being_slow(monkeypatch, notices):
    _row(hold_flagged_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "present")
    assert _sweep(48) == []
    assert assignments.state_of(_meta(), datetime.now(UTC)) == "held"


def test_a_holder_with_no_sign_expires_after_the_fallback_with_a_notice(monkeypatch, notices):
    _row(hold_flagged_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "unseen")
    assert _sweep(hold_sweep.FALLBACK_HOURS - 1) == []
    assert _sweep(hold_sweep.FALLBACK_HOURS + 1) == [(ROOM, KEY, "expired")]
    (notice,) = notices
    assert (notice["subkind"], notice["by"]) == ("expired", "coder")


def test_a_quiet_row_is_flagged_once_and_never_released(monkeypatch, notices):
    from app.services.room_channels import manager

    _row()
    posted: list[str] = []

    class Managed:
        async def post(self, _envelope: Any, text: str, **_kw: Any) -> None:
            posted.append(text)

    monkeypatch.setattr(manager, "get", lambda _r: Managed())
    monkeypatch.setattr(manager, "enqueue_herdr_wakes_for_mentions", lambda *_a, **_kw: [])
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "present")
    monkeypatch.setattr(hold_sweep, "last_activity", lambda *_a: datetime.now(UTC))

    assert _sweep(1) == []
    assert _sweep(hold_sweep.FLAG_HOURS + 1) == [(ROOM, KEY, "flagged")]
    (line,) = posted
    assert line.startswith("@lead @~coder has held this for 3h with no activity")
    # Once per hold, and the row is still held.
    assert _sweep(hold_sweep.FLAG_HOURS + 2) == []
    assert assignments.state_of(_meta(), datetime.now(UTC)) == "held"


def test_a_lease_drains_by_its_clock_not_this_sweep(monkeypatch, notices):
    _row(
        assignment="held",
        owner="@coder",
        claimed_at=datetime.now(UTC).isoformat(),
        ttl_minutes=30,
    )
    monkeypatch.setattr(hold_sweep, "signal_of", lambda _r, _h: "closed")
    assert _sweep(0) == []


def test_the_signal_is_read_off_the_runners_machine_reports(monkeypatch):
    from app.services import principals, runners
    from app.services.room_channels import manager

    registry = RunnerRegistry()
    monkeypatch.setattr(runners, "registry", registry)
    monkeypatch.setattr(principals, "classify_sender", lambda _r, _h: "agent")
    monkeypatch.setattr(manager, "herdr_status", lambda _r, _h: None)
    monkeypatch.setattr(manager, "members", lambda _r: [])

    def report(state: Literal["working", "gone"]) -> None:
        registry.hello(
            RunnerHello(
                id="mac",
                label="Mac",
                machine=MachineReportRead(
                    machine="mac",
                    workspaces=[
                        MachineWorkspaceRead(
                            id="w1",
                            label="w1",
                            room=ROOM,
                            agents=[
                                MachineAgentRead(
                                    handle="coder", room=ROOM, pane="w1:p1", state=state
                                )
                            ],
                        )
                    ],
                ),
            )
        )

    assert hold_sweep.signal_of(ROOM, "coder") == "unseen"
    report("working")
    assert hold_sweep.signal_of(ROOM, "coder") == "present"
    report("gone")
    assert hold_sweep.signal_of(ROOM, "coder") == "closed"


def test_reassigning_says_who_it_was_taken_from(notices):
    from app.services import fields

    _row()
    with pytest.raises(fields.FieldError) as refused:
        asyncio.run(fields.write(ROOM, KEY, {"assignee": "scout"}, "lead"))
    assert refused.value.status == 409
    assert "held by @coder" in refused.value.reason

    asyncio.run(fields.write(ROOM, KEY, {"assignee": "scout"}, "lead", reassign=True))
    assert assignments.holder(_meta(), datetime.now(UTC)) == "scout"
    (notice,) = notices
    assert notice["subkind"] == "claimed"
    assert (notice["for"], notice["from"], notice["by"]) == ("scout", "coder", "lead")


def test_claiming_a_row_given_to_someone_else_is_refused():
    _row()
    with pytest.raises(assignments.AssignmentError) as refused:
        asyncio.run(assignments.claim(ROOM, KEY, "scout", None, datetime.now(UTC)))
    assert refused.value.status == 409
    assert "assigned to @coder" in refused.value.reason
