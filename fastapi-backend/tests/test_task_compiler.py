# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the consensus→tasks compiler.

Pure-function tests run always; the live-LLM test is gated on
``MYCELIUM_LLM_TESTS=1`` (costs tokens).
"""

import os
from unittest.mock import patch

import pytest

from app.services import task_compiler


class TestBuildPrompt:
    def test_first_run_has_no_renegotiation_block(self):
        prompt = task_compiler._build_prompt(
            assignments={"scope": "full"},
            joined_intents="- alice: ship fast",
            issue_options=None,
            open_work=None,
        )
        assert "RE-NEGOTIATION" not in prompt
        assert "scope: full" in prompt
        assert "alice: ship fast" in prompt

    def test_renegotiation_block_embeds_the_open_work(self):
        prompt = task_compiler._build_prompt(
            assignments={"scope": "reduced"},
            joined_intents="",
            issue_options={"scope": ["full", "reduced"]},
            open_work="- [ ] still open\n",
        )
        assert "RE-NEGOTIATION" in prompt
        assert "still open" in prompt
        assert "full, reduced" in prompt

    def test_it_asks_for_lines_only(self):
        # The model's output is parsed into rows, so a heading or prose is
        # something the parser will drop rather than something it can use.
        prompt = task_compiler._build_prompt(
            assignments={}, joined_intents="", issue_options=None, open_work=None
        )
        assert "no heading" in prompt


class TestParseTasks:
    def test_reads_the_title_and_the_assignee(self):
        assert task_compiler.parse_tasks("- [ ] ship it @dana") == [
            task_compiler.CompiledTask(title="ship it", assignee="dana")
        ]

    def test_accepts_an_asterisk_bullet(self):
        assert task_compiler.parse_tasks("* [ ] ship it")[0].title == "ship it"

    def test_lowercases_the_handle(self):
        assert task_compiler.parse_tasks("- [ ] ship @Dana")[0].assignee == "dana"

    def test_drops_dangling_punctuation_left_by_the_handle(self):
        assert task_compiler.parse_tasks("- [ ] ship it — @dana")[0].title == "ship it"

    def test_ignores_anything_that_is_not_a_checklist_line(self):
        # A heading or a stray sentence is not a task, and turning one into a
        # row would put work in the room nobody asked for.
        body = "# Plan\n\nHere is what we agreed.\n- [ ] real task\n\n> a note"
        assert [t.title for t in task_compiler.parse_tasks(body)] == ["real task"]

    def test_ignores_a_line_that_is_only_a_handle(self):
        assert task_compiler.parse_tasks("- [ ] @dana") == []

    def test_ignores_an_empty_line(self):
        assert task_compiler.parse_tasks("- [ ]   ") == []

    def test_drops_a_task_that_arrives_already_finished(self):
        # The compiler produces work to do; a `- [x]` line is the model
        # narrating rather than agreeing.
        assert [t.title for t in task_compiler.parse_tasks("- [x] done\n- [ ] to do")] == ["to do"]

    def test_de_duplicates_case_insensitively(self):
        assert len(task_compiler.parse_tasks("- [ ] Ship It\n- [ ] ship it")) == 1


class TestFallbackTasks:
    def test_one_task_per_assignment(self):
        tasks = task_compiler.fallback_tasks({"scope": "full", "timeline": "6mo"})
        assert [t.title for t in tasks] == ["scope: full", "timeline: 6mo"]

    def test_empty_assignments_still_actionable(self):
        assert len(task_compiler.fallback_tasks({})) == 1

    def test_the_fallback_never_assigns(self):
        # It has no participant list to check a handle against, and inventing
        # one is the failure the compiler's prompt already guards.
        assert all(t.assignee is None for t in task_compiler.fallback_tasks({"a": "b"}))


class TestStripFences:
    def test_strips_markdown_fence(self):
        assert task_compiler._strip_fences("```markdown\n- [ ] a\n```") == "- [ ] a"

    def test_leaves_plain_text_alone(self):
        assert task_compiler._strip_fences("- [ ] a") == "- [ ] a"


@pytest.mark.asyncio
class TestCompileTasks:
    async def _compile(self, output: str):
        with patch.object(task_compiler, "_pi_complete", return_value=output):
            return await task_compiler.compile_tasks(
                room_name="r",
                assignments={"scope": "full"},
                joined_intents="",
                issue_options=None,
                open_work=None,
            )

    async def test_strips_fences_and_returns_tasks(self):
        tasks = await self._compile("```markdown\n- [ ] ship @dana\n```")
        assert tasks == [task_compiler.CompiledTask(title="ship", assignee="dana")]

    async def test_empty_content_raises(self):
        with pytest.raises(RuntimeError):
            await self._compile("   ")

    async def test_output_with_no_task_lines_raises(self):
        # Prose that parses to nothing must reach the caller's fail-soft path,
        # not silently compile a room's consensus into no work at all.
        with pytest.raises(RuntimeError):
            await self._compile("I think the team should consider its options.")


@pytest.mark.skipif(
    os.getenv("MYCELIUM_LLM_TESTS") != "1",
    reason="live LLM test — set MYCELIUM_LLM_TESTS=1 to run",
)
@pytest.mark.asyncio
async def test_compile_tasks_live():
    """Real compile against the configured model (exercises the live Pi path)."""
    tasks = await task_compiler.compile_tasks(
        room_name="live-test",
        assignments={"scope": "reduced", "timeline": "6mo"},
        joined_intents="- alice: ship a small scope fast\n- bob: keep quality high",
        issue_options={"scope": ["full", "reduced"], "timeline": ["3mo", "6mo"]},
        open_work=None,
    )
    assert tasks
    assert all(t.title for t in tasks)
