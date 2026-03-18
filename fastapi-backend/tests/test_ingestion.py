"""
Tests for Phase 8 additions:
- MEMORY_OPERATION audit type (schema change)
- POST /api/knowledge/ingest endpoint
- IngestionService._build_compact_payload() unit tests
"""

from unittest.mock import MagicMock, patch

from httpx import AsyncClient

from app.knowledge.ingestion import IngestionService

# ── MEMORY_OPERATION audit type ───────────────────────────────────────────────


AUDIT_BASE = {
    "resource_type": "MAS",
    "resource_identifier": "mas-abc",
    "audit_resource_identifier": "mas-abc",
    "created_by": "00000000-0000-0000-0000-000000000001",
    "last_modified_by": "00000000-0000-0000-0000-000000000001",
}


async def test_audit_memory_operation_accepted(client: AsyncClient):
    """MEMORY_OPERATION must now be accepted by the audit endpoint (was missing)."""
    resp = await client.post(
        "/api/internal/audit-events",
        json={**AUDIT_BASE, "audit_type": "MEMORY_OPERATION"},
    )
    assert resp.status_code == 200


async def test_audit_invalid_type_still_rejected(client: AsyncClient):
    """Unrecognised audit types must still return 400."""
    resp = await client.post(
        "/api/internal/audit-events",
        json={**AUDIT_BASE, "audit_type": "TOTALLY_MADE_UP"},
    )
    assert resp.status_code == 400


# ── IngestionService._build_compact_payload ───────────────────────────────────
# These are synchronous unit tests; the module-level asyncio mark is suppressed
# per-test via pytest.mark.asyncio(mode="auto") not applying to sync functions.


def _svc() -> IngestionService:
    return IngestionService(api_key=None, model="claude-sonnet-4-6")


def test_compact_payload_bare_turn():
    records = [{"userMessage": "hello", "response": "hi", "thinking": "..."}]
    result = _svc()._build_compact_payload(records)
    assert len(result) == 1
    assert result[0]["userMessage"] == "hello"
    assert result[0]["response"] == "hi"
    assert result[0]["thinking"] == "..."


def test_compact_payload_wrapped_turns():
    """Records with a top-level 'turns' list should be flattened."""
    records = [
        {
            "turns": [
                {"userMessage": "q1", "response": "a1"},
                {"userMessage": "q2", "response": "a2"},
            ]
        }
    ]
    result = _svc()._build_compact_payload(records)
    assert len(result) == 2
    assert result[0]["userMessage"] == "q1"
    assert result[1]["userMessage"] == "q2"


def test_compact_payload_tool_calls_stripped():
    """toolCalls are kept but stripped to id/name/input/result only."""
    records = [
        {
            "response": "done",
            "toolCalls": [
                {
                    "id": "tc1",
                    "name": "search",
                    "input": {"q": "x"},
                    "result": "y",
                    "extra": "drop_me",
                }
            ],
        }
    ]
    result = _svc()._build_compact_payload(records)
    assert len(result) == 1
    tc = result[0]["toolCalls"][0]
    assert tc == {"id": "tc1", "name": "search", "input": {"q": "x"}, "result": "y"}
    assert "extra" not in tc


def test_compact_payload_empty_turn_skipped():
    """Turns with no recognised fields produce no output entry."""
    records = [{"irrelevant_key": "ignored"}]
    result = _svc()._build_compact_payload(records)
    assert result == []


def test_compact_payload_empty_records():
    assert _svc()._build_compact_payload([]) == []


# ── POST /api/knowledge/ingest ────────────────────────────────────────────────

INGEST_BASE = {
    "workspace_id": "00000000-0000-0000-0000-000000000001",
    "mas_id": "00000000-0000-0000-0000-000000000002",
    "records": [{"userMessage": "what is X?", "response": "X is Y."}],
}


async def test_ingest_no_api_key_returns_zero_counts(client: AsyncClient):
    """When ANTHROPIC_API_KEY is unset the endpoint succeeds with 0 counts."""
    with patch("app.routes.knowledge.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"
        resp = await client.post("/api/knowledge/ingest", json=INGEST_BASE)

    assert resp.status_code == 200
    body = resp.json()
    assert body["concepts_extracted"] == 0
    assert body["relations_extracted"] == 0
    assert "graph_name" in body


async def test_ingest_empty_records_returns_zero_counts(client: AsyncClient):
    """Empty records list → 0 counts without calling LLM."""
    payload = {**INGEST_BASE, "records": []}
    with patch("app.routes.knowledge.settings") as mock_settings:
        mock_settings.LLM_API_KEY = None
        mock_settings.LLM_MODEL = "anthropic/claude-sonnet-4-6"
        resp = await client.post("/api/knowledge/ingest", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["concepts_extracted"] == 0
    assert body["relations_extracted"] == 0


async def test_ingest_missing_required_fields(client: AsyncClient):
    """mas_id is required — omitting it returns 422."""
    resp = await client.post(
        "/api/knowledge/ingest",
        json={"workspace_id": "00000000-0000-0000-0000-000000000001", "records": []},
    )
    assert resp.status_code == 422


async def test_ingest_with_mocked_llm(client: AsyncClient):
    """With a mocked Anthropic client, extracted concepts/relations are stored."""
    # Build fake tool-use blocks for both LLM stages
    fake_concepts_block = MagicMock()
    fake_concepts_block.type = "tool_use"
    fake_concepts_block.name = "record_concepts"
    fake_concepts_block.input = {
        "concepts": [
            {"name": "X", "type": "entity", "description": "The concept X"},
            {"name": "Y", "type": "fact", "description": "The fact Y"},
        ]
    }

    fake_rel_block = MagicMock()
    fake_rel_block.type = "tool_use"
    fake_rel_block.name = "record_relationships"
    fake_rel_block.input = {
        "relationships": [
            {"source": "X", "target": "Y", "relationship": "IS_DEFINED_AS", "description": "X is Y"}
        ]
    }

    fake_concepts_resp = MagicMock()
    fake_concepts_resp.content = [fake_concepts_block]

    fake_rel_resp = MagicMock()
    fake_rel_resp.content = [fake_rel_block]

    def _fake_create(**kwargs):
        tool_name = (kwargs.get("tool_choice") or {}).get("name", "")
        if tool_name == "record_concepts":
            return fake_concepts_resp
        return fake_rel_resp

    with (
        patch("app.routes.knowledge.settings") as mock_settings,
        patch("app.knowledge.ingestion.IngestionService._get_client") as mock_client,
        patch("app.knowledge.ingestion.kg_service.create_graph_store") as mock_store,
    ):
        mock_settings.ANTHROPIC_API_KEY = "sk-fake"
        mock_settings.COORDINATION_LLM_MODEL = "claude-sonnet-4-6"

        fake_anthropic = MagicMock()
        fake_anthropic.messages.create.side_effect = _fake_create
        mock_client.return_value = fake_anthropic

        mock_store_resp = MagicMock()
        mock_store_resp.status.value = "success"
        mock_store.return_value = mock_store_resp

        resp = await client.post("/api/knowledge/ingest", json=INGEST_BASE)

    assert resp.status_code == 200
    body = resp.json()
    assert body["concepts_extracted"] == 2
    assert body["relations_extracted"] == 1
    assert "graph_name" in body
