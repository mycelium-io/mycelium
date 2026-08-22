# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The room lifecycle bus: events in, room hooks out.

The bus is what lets an engine change a room's behaviour by being *registered*
rather than by being summoned. These cover the two guarantees the rest of the
feature rests on: a room with nothing installed exposes nothing (so the
un-guarded path stays the old path), and a listener that blows up cannot take
the emitting write down with it.
"""

import pytest

from app.services.engine_events import (
    SUMMON_FILTER,
    RoomEvent,
    RoomEventContext,
    RoomLifecycle,
)


@pytest.fixture
def bus() -> RoomLifecycle:
    return RoomLifecycle()


def test_room_with_no_install_exposes_no_hooks(bus):
    assert bus.hooks("quiet", SUMMON_FILTER) == []
    assert bus.owners("quiet", SUMMON_FILTER) == []


def test_install_is_scoped_to_the_room_and_keyed_by_owner(bus):
    def guard(_ctx):
        return {}

    bus.install("alpha", SUMMON_FILTER, "watcher", guard)
    assert bus.hooks("alpha", SUMMON_FILTER) == [guard]
    assert bus.owners("alpha", SUMMON_FILTER) == ["watcher"]
    # A second room is untouched.
    assert bus.hooks("beta", SUMMON_FILTER) == []


def test_reinstalling_the_same_owner_replaces_rather_than_stacks(bus):
    bus.install("alpha", SUMMON_FILTER, "watcher", lambda _c: {})
    replacement = lambda _c: {"a": "wake"}  # noqa: E731
    bus.install("alpha", SUMMON_FILTER, "watcher", replacement)
    assert bus.hooks("alpha", SUMMON_FILTER) == [replacement]


def test_uninstall_removes_only_that_owner(bus):
    first, second = lambda _c: {}, lambda _c: {}
    bus.install("alpha", SUMMON_FILTER, "one", first)
    bus.install("alpha", SUMMON_FILTER, "two", second)
    bus.uninstall("alpha", SUMMON_FILTER, "one")
    assert bus.owners("alpha", SUMMON_FILTER) == ["two"]
    # Removing an owner that never installed is a no-op, not an error.
    bus.uninstall("alpha", SUMMON_FILTER, "ghost")
    assert bus.owners("alpha", SUMMON_FILTER) == ["two"]


def test_emit_delivers_the_room_and_manifest_payload(bus):
    seen: list[RoomEventContext] = []
    bus.subscribe(RoomEvent.ENGINE_REGISTERED, seen.append)
    bus.emit(RoomEvent.ENGINE_REGISTERED, "alpha", handle="watcher", kind="summonguard")
    assert len(seen) == 1
    assert (seen[0].room, seen[0].handle, seen[0].kind) == ("alpha", "watcher", "summonguard")


def test_subscribing_the_same_listener_twice_delivers_once(bus):
    seen: list[RoomEventContext] = []
    bus.subscribe(RoomEvent.ROOM_PROVISIONED, seen.append)
    bus.subscribe(RoomEvent.ROOM_PROVISIONED, seen.append)
    bus.emit(RoomEvent.ROOM_PROVISIONED, "alpha")
    assert len(seen) == 1


def test_a_failing_listener_is_isolated_from_the_emitter_and_its_peers(bus):
    reached: list[str] = []

    def explodes(_ctx):
        raise RuntimeError("engine is broken")

    bus.subscribe(RoomEvent.ENGINE_REGISTERED, explodes)
    bus.subscribe(RoomEvent.ENGINE_REGISTERED, lambda ctx: reached.append(ctx.room))
    # The memory write that emitted this must not see the exception.
    bus.emit(RoomEvent.ENGINE_REGISTERED, "alpha")
    assert reached == ["alpha"]


def test_emit_with_no_subscribers_is_inert(bus):
    bus.emit(RoomEvent.ENGINE_REMOVED, "alpha", handle="watcher")
