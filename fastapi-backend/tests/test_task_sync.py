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

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import message_format, task_sync, tasks
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_memory_files,
    read_memory_file,
)
from app.services.message_models import Kind, MyceliumMessage
from app.services.task_compiler import CompiledTask
from tests.fakes import FakeManager


def _converged(assignments: dict, within: str | None = None) -> MyceliumMessage:
    """A ``commit:converged`` envelope carrying ``assignments`` (aligner output),
    and the task it was reached in when one is named."""
    data: dict = {"assignments": assignments, "metrics": {"mpc": 0.82}}
    if within:
        data["within"] = within
    return message_format.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode=message_format.episode_urn("r", "live"),
        recipients=["a", "b"],
        topic=message_format.topic_urn("r"),
        payload_type="consensus",
        payload_data=data,
    )


def _row(room: str, key: str):
    found = read_memory_file(get_room_dir(room), key)
    assert found is not None, f"expected a row at {key}"
    return found


async def _run(
    room: str,
    tasks: list[CompiledTask] | Exception,
    assignments: dict,
    within: str | None = None,
) -> list[str]:
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
        return await engine.compile_and_write(room, _converged(assignments, within))


class TestSlugify:
    def test_is_readable_and_stable(self):
        assert tasks.slugify("Ship the auth rewrite") == "ship-the-auth-rewrite"

    def test_collapses_punctuation(self):
        assert tasks.slugify("Ship auth (v2) — now!") == "ship-auth-v2-now"

    def test_never_returns_an_empty_key(self):
        assert tasks.slugify("!!!") == "task"

    def test_is_bounded(self):
        assert len(tasks.slugify("x" * 200)) <= tasks.SLUG_MAX


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
        assert meta["kind"] == tasks.TASK_KIND
        assert meta["status"] == "open"
        assert "ship auth" in body

    async def test_an_assignment_is_not_a_claim(self):
        # `owner` is the lease's: it says who is holding the row right now, under
        # rules this stage cannot satisfy. Writing it here would forge a claim
        # nobody made, and it would drain to "expired" on its own.
        await _run("r3", [CompiledTask(title="ship auth", assignee="a")], {"a": "auth"})
        meta, _ = _row("r3", "work/ship-auth")
        assert meta[tasks.ASSIGNEE_FIELD] == "@a"
        assert "owner" not in meta
        assert "assignment" not in meta

    async def test_an_untagged_task_names_nobody(self):
        await _run("r4", [CompiledTask(title="ship auth", assignee=None)], {"a": "auth"})
        meta, _ = _row("r4", "work/ship-auth")
        assert tasks.ASSIGNEE_FIELD not in meta

    async def test_a_recompiled_task_lands_on_the_row_it_already_has(self):
        task = [CompiledTask(title="ship auth", assignee="a")]
        await _run("r5", task, {"a": "auth"})
        keys = await _run("r5", task, {"a": "auth"})
        assert keys == ["work/ship-auth"]
        meta, _ = _row("r5", "work/ship-auth")
        assert meta["version"] == 2  # an upsert, not a second row

    async def test_a_row_gets_its_own_thread_not_the_negotiation_s(self):
        # The keystone, inverted: a compiled row is a task with its own thread,
        # minted when the row is written, not the episode the negotiation reached
        # its verdict in. Two tasks from one verdict are two threads, not two rows
        # sharing the conversation that produced them.
        await _run("r6", [CompiledTask(title="ship auth", assignee="a")], {"a": "auth"})
        meta, _ = _row("r6", "work/ship-auth")
        assert meta[EPISODE_META]
        assert meta[EPISODE_META] != message_format.episode_urn("r", "live")

    async def test_two_rows_from_one_verdict_are_two_threads(self):
        await _run(
            "r6b",
            [
                CompiledTask(title="ship auth", assignee="a"),
                CompiledTask(title="rotate keys", assignee="b"),
            ],
            {"a": "auth", "b": "keys"},
        )
        one = _row("r6b", "work/ship-auth")[0][EPISODE_META]
        two = _row("r6b", "work/rotate-keys")[0][EPISODE_META]
        assert one and two and one != two

    async def test_a_re_negotiation_does_not_move_a_row_off_its_thread(self):
        # A row's thread is where its history is. A later verdict that restates
        # the task must leave the binding alone, or the row loses the argument
        # that produced it.
        task = [CompiledTask(title="ship auth", assignee="a")]
        await _run("r7", task, {"a": "auth"})
        first = _row("r7", "work/ship-auth")[0][EPISODE_META]
        mgr = FakeManager()
        engine = task_sync.TaskSyncEngine(mgr)  # type: ignore[arg-type]
        later = message_format.build_envelope(
            kind=Kind.commit,
            subkind="converged",
            episode=message_format.episode_urn("r", "second"),
            recipients=["a"],
            topic=message_format.topic_urn("r"),
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


@pytest.mark.asyncio
class TestFiledUnderTheTask:
    """An agreement reached inside a task files its follow-up work under it."""

    async def test_rows_are_sub_tasks_of_the_task_named_within(self):
        await _run("r10", [CompiledTask(title="the parent", assignee=None)], {"x": "y"})
        await _run(
            "r10",
            [CompiledTask(title="send the offer", assignee="a")],
            {"decision": "15% off"},
            within="work/the-parent",
        )
        meta, _ = _row("r10", "work/send-the-offer")
        assert meta[task_sync.PARENT_RELATION] == "work/the-parent"

    async def test_without_within_rows_are_filed_as_before(self):
        await _run("r11", [CompiledTask(title="send the offer", assignee="a")], {"a": "x"})
        meta, _ = _row("r11", "work/send-the-offer")
        assert task_sync.PARENT_RELATION not in meta

    async def test_a_task_deleted_mid_run_is_not_pointed_at(self):
        await _run(
            "r12",
            [CompiledTask(title="send the offer", assignee="a")],
            {"decision": "15% off"},
            within="work/gone",
        )
        meta, _ = _row("r12", "work/send-the-offer")
        assert task_sync.PARENT_RELATION not in meta


@pytest.mark.asyncio
class TestOnlyTheAlignersAgreementIsCompiled:
    """A conductor's converged commit carries no ``assignments``: its decision
    is saved to memory, so the compile seam has nothing to file for it."""

    async def test_a_converged_commit_without_assignments_compiles_nothing(self):
        engine = task_sync.TaskSyncEngine(FakeManager())  # type: ignore[arg-type]
        commit = message_format.build_envelope(
            kind=Kind.commit,
            subkind="converged",
            episode=message_format.episode_urn("r13", "t1"),
            recipients=["a", "b"],
            topic=message_format.topic_urn("r13"),
            payload_type="outcome",
            payload_data={"protocol": "concord", "memory": "context/decision/x"},
        )
        compile_ = AsyncMock()
        with patch.object(task_sync.task_compiler, "compile_tasks", compile_):
            engine.handle_converged("r13", commit)
            await asyncio.sleep(0)
        assert not engine._tasks
        compile_.assert_not_called()
        assert not list_memory_files(get_room_dir("r13"), prefix="work/")

    async def test_the_aligners_agreement_still_compiles(self):
        engine = task_sync.TaskSyncEngine(FakeManager())  # type: ignore[arg-type]
        with patch.object(engine, "compile_and_write", AsyncMock(return_value=[])) as compiled:
            engine.handle_converged("r14", _converged({"price": "15%"}))
            await asyncio.gather(*engine._tasks)
        compiled.assert_awaited_once()
