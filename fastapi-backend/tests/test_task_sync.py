# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the converged→tasks consumer.

Fast unit tests (the merge gate — no node): a ``commit:converged`` fired through
the consumer compiles the agreement into ``work/`` rows (LLM mocked, as the
task-compiler tests do), and fails soft to the raw agreement when the compiler
is down.

The property underneath: consensus has to land as something a person or an
agent can pick up. A row carries an owner, a status and a lease; a line in a
shared document carries none of them.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import l9, task_sync, units
from app.services.filesystem import EPISODE_META, get_room_dir, read_memory_file
from app.services.l9_models import L9, Kind
from app.services.task_compiler import CompiledTask
from tests.fakes import FakeManager


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


def _row(room: str, key: str):
    found = read_memory_file(get_room_dir(room), key)
    assert found is not None, f"expected a row at {key}"
    return found


async def _run(room: str, tasks: list[CompiledTask] | Exception, assignments: dict) -> list[str]:
    mgr = FakeManager()
    engine = task_sync.TaskSyncEngine(mgr)  # type: ignore[arg-type]
    mock = (
        AsyncMock(side_effect=tasks)
        if isinstance(tasks, Exception)
        else AsyncMock(return_value=tasks)
    )
    with (
        patch.object(task_sync.task_compiler, "compile_tasks", mock),
        # Writing a row embeds it; these tests run without a model.
        patch("app.routes.memory.embed_text", return_value=[0.0]),
    ):
        return await engine.compile_and_write(room, _converged(assignments))


class TestSlugify:
    def test_is_readable_and_stable(self):
        assert units.slugify("Ship the auth rewrite") == "ship-the-auth-rewrite"

    def test_collapses_punctuation(self):
        assert units.slugify("Ship auth (v2) — now!") == "ship-auth-v2-now"

    def test_never_returns_an_empty_key(self):
        assert units.slugify("!!!") == "task"

    def test_is_bounded(self):
        assert len(units.slugify("x" * 200)) <= units.SLUG_MAX


@pytest.mark.asyncio
class TestConvergedToRows:
    async def test_each_task_becomes_its_own_row(self):
        keys = await _run(
            "r1",
            [
                CompiledTask(title="ship auth", assignee="a"),
                CompiledTask(title="write docs", assignee="b"),
            ],
            {"a": "auth", "b": "docs"},
        )
        assert keys == ["work/ship-auth", "work/write-docs"]

    async def test_a_row_carries_what_makes_it_a_row(self):
        await _run("r2", [CompiledTask(title="ship auth", assignee="a")], {"a": "auth"})
        meta, body = _row("r2", "work/ship-auth")
        assert meta["kind"] == units.TASK_KIND
        assert meta["status"] == "open"
        assert "ship auth" in body

    async def test_an_assignment_is_not_a_claim(self):
        # `owner` is the lease's: it says who is holding the row right now, under
        # rules this stage cannot satisfy. Writing it here would forge a claim
        # nobody made, and it would drain to "expired" on its own.
        await _run("r3", [CompiledTask(title="ship auth", assignee="a")], {"a": "auth"})
        meta, _ = _row("r3", "work/ship-auth")
        assert meta[units.ASSIGNEE_FIELD] == "@a"
        assert "owner" not in meta
        assert "custody" not in meta

    async def test_an_untagged_task_names_nobody(self):
        await _run("r4", [CompiledTask(title="ship auth", assignee=None)], {"a": "auth"})
        meta, _ = _row("r4", "work/ship-auth")
        assert units.ASSIGNEE_FIELD not in meta

    async def test_a_recompiled_task_lands_on_the_row_it_already_has(self):
        task = [CompiledTask(title="ship auth", assignee="a")]
        await _run("r5", task, {"a": "auth"})
        keys = await _run("r5", task, {"a": "auth"})
        assert keys == ["work/ship-auth"]
        meta, _ = _row("r5", "work/ship-auth")
        assert meta["version"] == 2  # an upsert, not a second row

    async def test_a_row_is_bound_to_the_episode_it_was_agreed_in(self):
        # The keystone: a compiled row is born inside a negotiation, so that
        # negotiation is the thread the row starts life in. Read off the
        # envelope's own header rather than minted, so work → episode → messages
        # round-trips back to the conversation that produced it.
        await _run("r6", [CompiledTask(title="ship auth", assignee="a")], {"a": "auth"})
        meta, _ = _row("r6", "work/ship-auth")
        assert meta[EPISODE_META] == l9.episode_urn("r", "live")

    async def test_a_re_negotiation_does_not_move_a_row_off_its_thread(self):
        # A row's thread is where its history is. A later verdict that restates
        # the task must leave the binding alone, or the row loses the argument
        # that produced it.
        task = [CompiledTask(title="ship auth", assignee="a")]
        await _run("r7", task, {"a": "auth"})
        first = _row("r7", "work/ship-auth")[0][EPISODE_META]
        mgr = FakeManager()
        engine = task_sync.TaskSyncEngine(mgr)  # type: ignore[arg-type]
        later = l9.build_envelope(
            kind=Kind.commit,
            subkind="converged",
            episode=l9.episode_urn("r", "second"),
            recipients=["a"],
            topic=l9.topic_urn("r"),
            payload_type="consensus",
            payload_data={"assignments": {"a": "auth"}},
        )
        with (
            patch.object(task_sync.task_compiler, "compile_tasks", AsyncMock(return_value=task)),
            patch("app.routes.memory.embed_text", return_value=[0.0]),
        ):
            await engine.compile_and_write("r7", later)
        assert _row("r7", "work/ship-auth")[0][EPISODE_META] == first

    async def test_a_rewrite_does_not_reopen_work_somebody_moved(self):
        # A re-negotiation that restates an untouched task must not undo a
        # resolution somebody already recorded against it.
        task = [CompiledTask(title="ship auth", assignee="a")]
        await _run("r6", task, {"a": "auth"})
        from app.services.fields import write as write_fields

        await write_fields("r6", "work/ship-auth", {"status": "resolved"}, "dana")
        await _run("r6", task, {"a": "auth"})
        meta, _ = _row("r6", "work/ship-auth")
        assert meta["status"] == "resolved"


@pytest.mark.asyncio
class TestFailSoft:
    async def test_a_compiler_outage_still_records_the_agreement(self):
        # The verdict is the expensive part; losing it because one LLM call
        # failed would sink a whole negotiation.
        keys = await _run("r7", RuntimeError("pi is down"), {"scope": "reduced"})
        assert keys == ["work/scope-reduced"]
        _meta, body = _row("r7", "work/scope-reduced")
        assert "scope: reduced" in body


@pytest.mark.asyncio
class TestOpenWork:
    async def test_it_lists_only_unfinished_rows(self):
        await _run(
            "r8",
            [
                CompiledTask(title="ship auth", assignee=None),
                CompiledTask(title="write docs", assignee=None),
            ],
            {},
        )
        from app.services.fields import write as write_fields

        await write_fields("r8", "work/write-docs", {"status": "resolved"}, "dana")
        assert task_sync.open_work_markdown("r8") == "- [ ] ship auth"

    async def test_a_room_with_no_work_offers_nothing_to_the_prompt(self):
        assert task_sync.open_work_markdown("r9-empty") is None
