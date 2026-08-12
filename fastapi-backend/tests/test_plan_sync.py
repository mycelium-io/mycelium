# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the converged→plan→memory-sync consumer.

Fast unit tests (the merge gate — no node): a ``commit:converged`` fired through
the consumer compiles ``plan/tasks.md`` (LLM mocked, as the plan-compiler tests
do), broadcasts it as a ``knowledge`` push, and fails soft to the raw agreement
when the compiler is down.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import l9, memory_sync, plan, plan_sync
from app.services.filesystem import get_room_dir, read_memory_file
from app.services.l9_models import L9, Kind


def _converged(assignments: dict) -> L9:
    """A ``commit:converged`` envelope carrying ``assignments`` (aligner output)."""
    return l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode=l9.episode_urn("r", "live"),
        recipients=["a", "b"],
        topic=l9.topic_urn("r"),
        payload_type="consensus",
        payload_data={"assignments": assignments, "metrics": {"mpc": 0.82}},
    )


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, envelope, *, extra=None) -> None:
        self.sent.append((envelope, extra))


class _FakeManaged:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.persister = None


class _FakeManager:
    """Just enough of RoomChannelManager for the consumer: get + members."""

    def __init__(self, *, live: bool = True) -> None:
        self.channel = _FakeChannel()
        self._managed = _FakeManaged(self.channel) if live else None

    def get(self, room):
        return self._managed

    def members(self, room):
        return ["a", "b"]


@pytest.mark.asyncio
class TestConvergedToPlan:
    async def test_compiles_plan_file_with_expected_tasks(self):
        mgr = _FakeManager()
        engine = plan_sync.PlanSyncEngine(mgr)  # type: ignore[arg-type]
        fake_plan = "# MVP Delivery\n\n- [ ] ship auth @a\n- [ ] write docs @b"
        with patch.object(
            plan_sync.plan_compiler, "compile_plan", AsyncMock(return_value=fake_plan)
        ):
            write = await engine.compile_and_sync("r", _converged({"a": "auth", "b": "docs"}))

        got = read_memory_file(get_room_dir("r"), plan_sync.PLAN_TASKS_KEY)
        assert got is not None
        meta, body = got
        assert "ship auth @a" in body and "write docs @b" in body
        assert meta["version"] == 1
        # The compiled plan also became a knowledge push carrying its content.
        assert write is not None and write.content.startswith("# MVP Delivery")
        assert len(mgr.channel.sent) == 1
        env, _extra = mgr.channel.sent[0]
        assert env.header.kind == Kind.knowledge
        carried = memory_sync.knowledge_write_from_envelope(env)
        assert carried is not None and carried.version == 1 and carried.base_version is None

    async def test_sets_plan_title_from_heading(self):
        mgr = _FakeManager()
        engine = plan_sync.PlanSyncEngine(mgr)  # type: ignore[arg-type]
        with patch.object(
            plan_sync.plan_compiler,
            "compile_plan",
            AsyncMock(return_value="# Sprint Plan\n\n- [ ] x"),
        ):
            await engine.compile_and_sync("r", _converged({"a": "x"}))
        assert plan.get_title("r") == "Sprint Plan"

    async def test_recompile_bumps_version_and_threads_base(self):
        mgr = _FakeManager()
        engine = plan_sync.PlanSyncEngine(mgr)  # type: ignore[arg-type]
        with patch.object(
            plan_sync.plan_compiler,
            "compile_plan",
            AsyncMock(side_effect=["# Plan\n\n- [ ] one", "# Plan\n\n- [ ] two"]),
        ):
            await engine.compile_and_sync("r", _converged({"a": "one"}))
            write2 = await engine.compile_and_sync("r", _converged({"a": "two"}))

        got = read_memory_file(get_room_dir("r"), plan_sync.PLAN_TASKS_KEY)
        assert got is not None and got[0]["version"] == 2 and "two" in got[1]
        assert write2 is not None and write2.version == 2 and write2.base_version == 1

    async def test_fail_soft_compile_falls_back_to_raw_agreement(self):
        """A compiler outage must not sink the verdict — write the raw agreement."""
        mgr = _FakeManager()
        engine = plan_sync.PlanSyncEngine(mgr)  # type: ignore[arg-type]
        with patch.object(
            plan_sync.plan_compiler,
            "compile_plan",
            AsyncMock(side_effect=RuntimeError("LLM down")),
        ):
            # Must not raise.
            write = await engine.compile_and_sync(
                "r", _converged({"scope": "full", "timeline": "6mo"})
            )

        got = read_memory_file(get_room_dir("r"), plan_sync.PLAN_TASKS_KEY)
        assert got is not None
        body = got[1]
        # fallback_body renders the raw issue=value lines.
        assert "scope: full" in body and "timeline: 6mo" in body
        assert write is not None

    async def test_converged_adapter_binds_room_like_summon_seam(self):
        """The manager's ``on_converged`` adapter injects the room the persister
        can't (mirrors the summon adapter)."""
        from app.services.room_channels import RoomChannelManager

        mgr = RoomChannelManager(endpoint="http://x", default_workspace="ws")
        seen: list = []
        mgr.on_converged = lambda room, env: seen.append((room, env))
        adapter = mgr._converged_adapter("room-x")
        assert adapter is not None
        env = _converged({"a": "x"})
        adapter(env)  # persister calls with (envelope) only
        assert seen == [("room-x", env)]
        # No hook wired → no adapter (persister keeps its log-only default).
        mgr.on_converged = None
        assert mgr._converged_adapter("room-x") is None

    async def test_no_channel_writes_plan_but_skips_broadcast(self):
        mgr = _FakeManager(live=False)
        engine = plan_sync.PlanSyncEngine(mgr)  # type: ignore[arg-type]
        with patch.object(
            plan_sync.plan_compiler, "compile_plan", AsyncMock(return_value="# P\n\n- [ ] a")
        ):
            write = await engine.compile_and_sync("r", _converged({"a": "a"}))
        # Plan still written locally; no knowledge push (nothing to broadcast to).
        assert read_memory_file(get_room_dir("r"), plan_sync.PLAN_TASKS_KEY) is not None
        assert write is None
