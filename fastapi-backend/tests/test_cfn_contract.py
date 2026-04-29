# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Contract tests against the live CFN cognition-fabric-node-svc.

Mycelium's coordination service depends on CFN's HTTP API contract — the JSON
shape of /start, /decide, and /shared-memories responses. CFN is shipped as
a separate image (``ghcr.io/outshift-open/ioc-cognition-fabric-node-svc``)
on its own release cadence, so we don't have natural visibility into changes
that could quietly break us.

These tests hit the running CFN container directly with the exact request
shapes mycelium-backend produces and assert the response shape is what we
expect. They are gated on ``MYCELIUM_CFN_CONTRACT_TESTS=1`` and a healthy
CFN container reachable at ``COGNITION_FABRIC_NODE_URL`` (default
``http://localhost:9002``) so they don't run in unit CI by default — they're
intended for:

  1. Local validation when bumping the CFN image version in compose.yml
  2. The dedicated ``cfn-contract.yml`` workflow that spins up CFN and runs
     them on every PR that touches the image pin

When the contract changes (CFN team ships a breaking response shape change),
these tests fail with a specific assertion pointing at the missing/renamed
field — which is the early-warning signal we want.

Captured fixtures live in ``tests/fixtures/cfn/<version>/`` and are useful
for diffing: when a test fails, the fixture from the last known-good version
shows what we used to receive vs what we got now. Update the fixtures in a
new ``tests/fixtures/cfn/<new-version>/`` directory when intentionally
adopting a new contract — don't overwrite the old ones.

See ``tests/fixtures/cfn/compatibility.md`` for the canonical "what CFN owes
us" inventory and version history.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import pytest

CFN_BASE_URL = os.environ.get("COGNITION_FABRIC_NODE_URL", "http://localhost:9002")
WORKSPACE_ID = os.environ.get("WORKSPACE_ID", "")
MAS_ID = os.environ.get("CFN_CONTRACT_MAS_ID", "")
ENABLED = os.environ.get("MYCELIUM_CFN_CONTRACT_TESTS", "").lower() in ("1", "true", "yes")

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cfn"

pytestmark = pytest.mark.skipif(
    not ENABLED,
    reason="set MYCELIUM_CFN_CONTRACT_TESTS=1 + WORKSPACE_ID + CFN_CONTRACT_MAS_ID to run",
)


def _api(path: str) -> str:
    """Build a fully qualified CFN API URL for the configured workspace + MAS."""
    return f"{CFN_BASE_URL}/api/workspaces/{WORKSPACE_ID}/multi-agentic-systems/{MAS_ID}{path}"


@pytest.fixture(scope="module")
def session_id() -> str:
    """Unique session id per test run so reruns don't collide."""
    return f"contract-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def cfn_started_session(session_id: str) -> dict:
    """Hit /start once and yield the response for downstream contract checks.

    Module-scoped because /start is non-idempotent (it allocates a session in
    CFN); we want every test to share the same baseline response.
    """
    body = {
        "session_id": session_id,
        "content_text": (
            "Pick a database (Postgres or DynamoDB) and a timeline "
            "(3-month or 6-month). Decide together."
        ),
        "agents": [
            {"id": "alice", "name": "Alice"},
            {"id": "bob", "name": "Bob"},
        ],
        "n_steps": 5,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(_api("/semantic-negotiation/start"), json=body)
    assert resp.status_code == 200, f"CFN /start returned {resp.status_code}: {resp.text[:500]}"
    return resp.json()


# ── /start contract ─────────────────────────────────────────────────────────


def test_start_top_level_shape(cfn_started_session: dict) -> None:
    """The top-level /start response keys must include everything coordination.py reads.

    See ``app/services/coordination.py:_run_cfn_negotiation`` and
    ``_fan_out_cfn_messages`` — they read:
      - status, session_id, n_steps, round (for state)
      - issues, options_per_issue (parent-level fallback for ticks)
      - messages (the broadcast tick array)
    """
    r = cfn_started_session
    expected_keys = {
        "status",
        "session_id",
        "issues",
        "options_per_issue",
        "n_steps",
        "round",
        "messages",
    }
    missing = expected_keys - set(r.keys())
    assert not missing, f"CFN /start missing top-level keys: {missing} — got {sorted(r.keys())}"
    assert r["status"] == "initiated", f"unexpected /start status: {r['status']!r}"
    assert isinstance(r["issues"], list) and r["issues"], "issues must be a non-empty list"
    assert isinstance(r["options_per_issue"], dict) and r["options_per_issue"]
    assert isinstance(r["messages"], list) and r["messages"]
    assert isinstance(r["n_steps"], int) and r["n_steps"] > 0
    assert isinstance(r["round"], int) and r["round"] >= 0


def test_start_message_envelope_shape(cfn_started_session: dict) -> None:
    """Each entry in messages[] must be a valid SSTPNegotiateMessage envelope.

    coordination.py:_fan_out_cfn_messages reads ``msg.payload``, ``msg.semantic_context``,
    and uses ``payload.participant_id`` to detect broadcast (server) vs targeted
    ticks. If any of these envelope keys move, our tick fan-out breaks silently.
    """
    msg = cfn_started_session["messages"][0]
    expected_keys = {
        "version",
        "message_id",
        "dt_created",
        "origin",
        "semantic_context",
        "payload_hash",
        "policy_labels",
        "provenance",
    }
    missing = expected_keys - set(msg.keys())
    assert not missing, f"message envelope missing keys: {missing} — got {sorted(msg.keys())}"


def test_start_semantic_context_shape(cfn_started_session: dict) -> None:
    """``semantic_context`` carries the negotiation space and SAO state.

    coordination.py reads ``semantic_context.issues``, ``options_per_issue``,
    and (transitively, via tick payload) state about the current offer.
    """
    sc = cfn_started_session["messages"][0].get("semantic_context", {})
    expected_keys = {
        "schema_id",
        "schema_version",
        "encoding",
        "session_id",
        "issues",
        "options_per_issue",
        "sao_state",
    }
    missing = expected_keys - set(sc.keys())
    assert not missing, f"semantic_context missing keys: {missing} — got {sorted(sc.keys())}"
    assert isinstance(sc["issues"], list)
    assert isinstance(sc["options_per_issue"], dict)
    # sao_state is a NegMAS state object — we don't deep-inspect, just assert it's a dict
    assert isinstance(sc["sao_state"], dict), (
        f"sao_state should be dict, got {type(sc['sao_state']).__name__}"
    )


# ── /decide contract ────────────────────────────────────────────────────────


def test_decide_returns_ongoing_when_unanimous_reject(
    session_id: str, cfn_started_session: dict
) -> None:
    """When all agents reject, /decide must return ``status: ongoing`` with new ticks.

    coordination.py:_cfn_decide_round branches on ``status`` ∈ {agreed, ongoing}.
    A new status string would fall into the "Unknown / failed status" branch and
    finish the session with broken=True — which is wrong if CFN added a new
    valid intermediate state.
    """
    # Fixture argument ensures /start ran first to allocate the session in CFN;
    # we rely on the session_id but cfn_started_session is what guarantees order.
    assert cfn_started_session["session_id"] == session_id
    body = {
        "session_id": session_id,
        "agent_replies": [
            {"agent_id": "alice", "participant_id": "alice", "action": "reject"},
            {"agent_id": "bob", "participant_id": "bob", "action": "reject"},
        ],
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(_api("/semantic-negotiation/decide"), json=body)
    assert resp.status_code == 200, f"CFN /decide returned {resp.status_code}: {resp.text[:500]}"
    r = resp.json()
    expected_keys = {"status", "session_id", "round", "messages"}
    missing = expected_keys - set(r.keys())
    assert not missing, f"/decide missing keys: {missing} — got {sorted(r.keys())}"
    assert r["status"] == "ongoing", (
        f"unanimous-reject /decide should be ongoing, got {r['status']!r}"
    )
    assert isinstance(r["messages"], list) and r["messages"], (
        "ongoing /decide should ship next-round ticks in messages[]"
    )


# ── /shared-memories contract ───────────────────────────────────────────────


def test_shared_memories_accepts_openclaw_payload() -> None:
    """The knowledge-extract hook posts openclaw-format records to /shared-memories.

    See ``app/routes/knowledge.py`` and the hook source. CFN must accept the
    request and return a 2xx with a response_id; the actual concept extraction
    happens async and isn't part of the contract we test here.
    """
    body = {
        "request_id": f"contract-{uuid.uuid4().hex[:8]}",
        "header": {"agent_id": "alice"},
        "payload": {
            "data": [
                {
                    "timestamp": "2026-04-28T00:00:00Z",
                    "agent_id": "alice",
                    "session_id": "contract-test",
                    "thinking": "contract test thinking content",
                }
            ],
            "metadata": {"format": "openclaw"},
        },
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(_api("/shared-memories"), json=body)
    assert resp.status_code == 201, (
        f"/shared-memories returned {resp.status_code}: {resp.text[:500]}"
    )
    r = resp.json()
    assert "response_id" in r, f"/shared-memories missing response_id: {r!r}"


# ── Fixture diff helper ─────────────────────────────────────────────────────


def test_start_response_shape_matches_fixture(cfn_started_session: dict) -> None:
    """Compare structural shape (keys + nested key sets) against the captured fixture.

    Values change between runs (UUIDs, timestamps, LLM-generated issue names) so
    we don't compare values — only the recursive shape of dict keys and list
    types. If CFN renames or removes a field, this test flags exactly which
    nested path changed, which is the most useful failure message for diagnosing
    a contract regression.
    """
    fixture_path = FIXTURE_DIR / "0.1.2" / "start_response.json"
    if not fixture_path.exists():
        pytest.skip(f"no captured fixture at {fixture_path}")

    fixture = json.loads(fixture_path.read_text())

    def shape(obj: object) -> object:
        if isinstance(obj, dict):
            return {k: shape(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [shape(obj[0])] if obj else []
        return type(obj).__name__

    expected_shape = shape(fixture)
    actual_shape = shape(cfn_started_session)
    if expected_shape != actual_shape:
        # Produce a key-level diff for easier debugging
        def keys_diff(exp: object, act: object, path: str = "") -> list[str]:
            if isinstance(exp, dict) and isinstance(act, dict):
                diffs = []
                for k in exp:
                    if k not in act:
                        diffs.append(f"  - missing: {path}.{k}")
                    else:
                        diffs.extend(keys_diff(exp[k], act[k], f"{path}.{k}"))
                for k in act:
                    if k not in exp:
                        diffs.append(f"  + new: {path}.{k}")
                return diffs
            if type(exp).__name__ != type(act).__name__:
                return [f"  type changed at {path}: {exp} -> {act}"]
            return []

        diffs = keys_diff(expected_shape, actual_shape)
        msg = "Response shape diverged from fixture:\n" + "\n".join(diffs[:20])
        if len(diffs) > 20:
            msg += f"\n  (... +{len(diffs) - 20} more)"
        pytest.fail(msg)
