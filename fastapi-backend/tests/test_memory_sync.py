# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the L9 ``knowledge`` memory-sync write path.

Fast unit tests (the merge gate — no node): the ``knowledge`` envelope shape, the
apply-to-local-store write + reindex, and the last-write-wins conflict policy
(idempotent same-version loopback; stale-base rejection with details, no merge).
"""

import pytest

from app.services import memory_sync, search_index
from app.services.filesystem import get_room_dir, read_memory_file
from app.services.l9_models import Kind


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Reindex here goes through the embedder; stub it so the apply→reindex tests
    never load the fastembed ONNX model (debt D12: it PermissionErrors writing to
    the ``/opt/fastembed`` cache in constrained/sandbox envs). CI already exports
    ``MYCELIUM_STUB_EMBEDDINGS``; this makes the file green without it too."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


def _write(
    key: str = "plan/tasks",
    *,
    version: int = 1,
    base: int | None = None,
    content="# Plan\n\n- [ ] x",
) -> memory_sync.KnowledgeWrite:
    return memory_sync.KnowledgeWrite(
        key=key,
        content=content,
        version=version,
        created_by="CognitiveEngine",
        updated_by="CognitiveEngine",
        updated_at="2026-08-04T00:00:00+00:00",
        base_version=base,
    )


class TestKnowledgeWrite:
    def test_payload_round_trip(self):
        w = _write(version=3, base=2)
        back = memory_sync.KnowledgeWrite.from_payload(w.to_payload())
        assert back is not None
        assert (back.key, back.content, back.version, back.base_version) == (
            w.key,
            w.content,
            3,
            2,
        )

    def test_from_payload_rejects_malformed(self):
        assert memory_sync.KnowledgeWrite.from_payload({"key": "", "content": "x"}) is None
        assert memory_sync.KnowledgeWrite.from_payload({"content": "x"}) is None
        assert memory_sync.KnowledgeWrite.from_payload({"key": "k"}) is None

    def test_from_payload_defaults_bad_version(self):
        back = memory_sync.KnowledgeWrite.from_payload(
            {"key": "k", "content": "c", "version": "nope"}
        )
        assert back is not None and back.version == 1


class TestKnowledgeEnvelope:
    def test_carries_the_write_as_knowledge_distillation(self):
        env = memory_sync.build_knowledge_envelope(room="r", write=_write(), recipients=["a", "b"])
        assert env.header.kind == Kind.knowledge
        assert env.header.subkind == memory_sync.KNOWLEDGE_SUBKIND
        assert memory_sync.is_knowledge(env)
        # Broadcast terminal push: no wire parents (releasable by everyone).
        assert env.header.message is not None and env.header.message.parents == []
        back = memory_sync.knowledge_write_from_envelope(env)
        assert back is not None and back.key == "plan/tasks"


@pytest.mark.asyncio
class TestApplyKnowledge:
    async def test_writes_markdown_and_reindexes_second_store(self):
        """A knowledge write lands as markdown AND updates the JSONL index."""
        result = await memory_sync.apply_knowledge(
            "second-store", _write(content="# Plan\n\n- [ ] ship it")
        )
        assert result.applied and not result.conflict

        got = read_memory_file(get_room_dir("second-store"), "plan/tasks")
        assert got is not None
        meta, body = got
        assert "ship it" in body
        assert meta["version"] == 1

        # Reindexed: the JSONL search index carries the new record.
        keys = {r["key"] for r in search_index.load_index("second-store")}
        assert "plan/tasks" in keys

    async def test_idempotent_same_version_loopback(self):
        """Re-applying the same version (same-machine emit→apply) is a no-op."""
        await memory_sync.apply_knowledge("r", _write(version=1))
        again = await memory_sync.apply_knowledge("r", _write(version=1, content="# Different"))
        assert not again.applied and not again.conflict
        # The original content is untouched — no clobber by an equal-version write.
        got = read_memory_file(get_room_dir("r"), "plan/tasks")
        assert got is not None and "# Different" not in got[1]

    async def test_newer_version_wins(self):
        await memory_sync.apply_knowledge("r", _write(version=1, content="# v1"))
        res = await memory_sync.apply_knowledge("r", _write(version=2, base=1, content="# v2 wins"))
        assert res.applied
        got = read_memory_file(get_room_dir("r"), "plan/tasks")
        assert got is not None and "v2 wins" in got[1] and got[0]["version"] == 2


class TestConflictPolicy:
    def test_stale_base_rejected_with_details_no_merge(self, tmp_path):
        """A write on a stale base fails with current details; nothing is merged."""
        base_dir = tmp_path / "store"
        base_dir.mkdir()
        # Local is already at version 3 (someone advanced it).
        memory_sync.apply_knowledge_to_dir(
            base_dir,
            memory_sync.KnowledgeWrite(
                key="plan/tasks",
                content="# current v3",
                version=3,
                created_by="alice",
                updated_by="alice",
                updated_at="2026-08-04T03:00:00+00:00",
            ),
        )
        # An incoming write built on base v1 → version 2, behind local v3.
        result = memory_sync.apply_knowledge_to_dir(
            base_dir, _write(version=2, base=1, content="# stale v2")
        )
        assert result.conflict and not result.applied
        assert result.current is not None
        assert result.current["version"] == 3
        assert result.current["updated_by"] == "alice"
        assert "current v3" in result.current["content"]
        # No merge: the local file still holds v3 verbatim.
        _meta, body = read_memory_file(base_dir, "plan/tasks")  # type: ignore[misc]
        assert body.strip() == "# current v3"
        # The rejection formats a log-ready line.
        assert "stale-base" in result.format_conflict()
