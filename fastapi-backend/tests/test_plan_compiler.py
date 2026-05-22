# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for the consensus→plan compiler.

Pure-function tests run always; the live-LLM test is gated on
``MYCELIUM_LLM_TESTS=1`` (costs tokens).
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import plan_compiler


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
        _hidden_params={},
    )


class TestBedrockDetection:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("bedrock/anthropic.claude-3", True),
            ("anthropic/bedrock/global.anthropic.claude-sonnet-4-6", True),
            ("BEDROCK/Anthropic.Claude", True),
            ("something.bedrock-runtime.us-east-1", True),
            ("anthropic/claude-sonnet-4-6", False),
            ("openai/gpt-4o", False),
            ("", False),
            (None, False),
        ],
    )
    def test_detection(self, model, expected):
        assert plan_compiler._model_uses_bedrock_sync_path(model) is expected


class TestBuildPrompt:
    def test_first_run_has_no_renegotiation_block(self):
        prompt = plan_compiler._build_prompt(
            assignments={"scope": "full"},
            joined_intents="- alice: ship fast",
            issue_options=None,
            existing_plan=None,
        )
        assert "RE-NEGOTIATION" not in prompt
        assert "scope: full" in prompt
        assert "alice: ship fast" in prompt

    def test_renegotiation_block_embeds_existing_plan(self):
        prompt = plan_compiler._build_prompt(
            assignments={"scope": "reduced"},
            joined_intents="",
            issue_options={"scope": ["full", "reduced"]},
            existing_plan="# Old plan\n\n- [x] done already\n- [ ] still open\n",
        )
        assert "RE-NEGOTIATION" in prompt
        assert "done already" in prompt
        assert "full, reduced" in prompt


class TestFallbackBody:
    def test_lists_each_assignment(self):
        body = plan_compiler.fallback_body({"scope": "full", "timeline": "6mo"})
        assert body.startswith("# Plan")
        assert "- [ ] scope: full" in body
        assert "- [ ] timeline: 6mo" in body

    def test_empty_assignments_still_actionable(self):
        body = plan_compiler.fallback_body({})
        assert "- [ ]" in body


class TestStripFences:
    def test_strips_markdown_fence(self):
        fenced = "```markdown\n# Plan\n\n- [ ] a\n```"
        assert plan_compiler._strip_fences(fenced) == "# Plan\n\n- [ ] a"

    def test_leaves_plain_text_alone(self):
        plain = "# Plan\n\n- [ ] a"
        assert plan_compiler._strip_fences(plain) == plain


@pytest.mark.asyncio
class TestCompilePlan:
    async def test_strips_fences_from_llm_output(self):
        with patch.object(
            plan_compiler,
            "_acompletion_compat",
            AsyncMock(return_value=_fake_response("```markdown\n# Plan\n\n- [ ] ship\n```")),
        ):
            body = await plan_compiler.compile_plan(
                room_name="r",
                assignments={"scope": "full"},
                joined_intents="",
                issue_options=None,
                existing_plan=None,
            )
        assert body == "# Plan\n\n- [ ] ship"

    async def test_empty_content_raises(self):
        with (
            patch.object(
                plan_compiler,
                "_acompletion_compat",
                AsyncMock(return_value=_fake_response("   ")),
            ),
            pytest.raises(RuntimeError),
        ):
            await plan_compiler.compile_plan(
                room_name="r",
                assignments={"scope": "full"},
                joined_intents="",
                issue_options=None,
                existing_plan=None,
            )


@pytest.mark.skipif(
    os.getenv("MYCELIUM_LLM_TESTS") != "1",
    reason="live LLM test — set MYCELIUM_LLM_TESTS=1 to run",
)
@pytest.mark.asyncio
async def test_compile_plan_live():
    """Real compile against the configured model (exercises the Bedrock sync path)."""
    body = await plan_compiler.compile_plan(
        room_name="live-test",
        assignments={"scope": "reduced", "timeline": "6mo"},
        joined_intents="- alice: ship a small scope fast\n- bob: keep quality high",
        issue_options={"scope": ["full", "reduced"], "timeline": ["3mo", "6mo"]},
        existing_plan=None,
    )
    assert body.lstrip().startswith("#")
    assert "- [ ]" in body
