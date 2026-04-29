# CFN HTTP API contract — what mycelium-backend depends on

This is the canonical inventory of CFN response fields that mycelium-backend
reads from `ioc-cognition-fabric-node-svc`. When the CFN team ships a new
version, the contract tests in `tests/test_cfn_contract.py` validate this
inventory against the running container; failures here mean a CFN change
silently broke us and we need to either follow the rename or pin to the
last working version.

## Endpoints we depend on

### `POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/start`

**Caller**: `app/services/cfn_negotiation.py:start_negotiation` →
`app/services/coordination.py:_run_cfn_negotiation`

**Reads**:
| Path | Used in | Required |
|---|---|---|
| `status` | `coordination.py` (logged; not branched on) | informational |
| `messages[]` | `_fan_out_cfn_messages` — broadcast to agents | ✅ required, non-empty |
| `messages[].payload.participant_id` | distinguishes server-broadcast (`"server"`) from targeted ticks | ✅ required |
| `messages[].payload.round` | tick payload forwarded to agents | ✅ required |
| `messages[].payload.action` | tick payload forwarded to agents (`"respond"` etc.) | ✅ required |
| `messages[].payload.allowed_actions` | tick payload forwarded to agents | ✅ required |
| `messages[].payload.next_proposer_id` | drives `can_counter_offer` per-agent | ✅ required |
| `messages[].payload.current_offer` | tick payload forwarded to agents | optional (None on round 0) |
| `messages[].payload.proposer_id` | tick payload forwarded to agents | optional |
| `messages[].semantic_context.issues` | per-message issue list (preferred over top-level) | ✅ required |
| `messages[].semantic_context.options_per_issue` | per-message options map | ✅ required |
| `messages[].semantic_context.sao_state` | not deeply inspected; sanity check it's a dict | ✅ required |
| `issues` | top-level fallback when message-level missing | required for fallback path |
| `options_per_issue` | top-level fallback when message-level missing | required for fallback path |

### `POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/decide`

**Caller**: `app/services/cfn_negotiation.py:decide_negotiation` →
`app/services/coordination.py:_cfn_decide_round`

**Reads**:
| Path | Used in | Required |
|---|---|---|
| `status` | branched on (`agreed` / `ongoing` / other → broken) | ✅ required |
| `messages[]` | when `status == "ongoing"`, fan out as next-round ticks | required when ongoing |
| `final_result.semantic_context.final_agreement[]` | when `status == "agreed"`, parsed as `{issue_id, chosen_option}` list | required when agreed |
| `payload.status` (nested envelope) | fallback for status when top-level missing | optional |

**Status values branched on**: `"agreed"`, `"ongoing"`. Anything else triggers a
broken-session terminator with `plan="Negotiation ended: <status>"`. **If CFN adds
a new intermediate status, we will treat it as failure** — the contract test
`test_decide_returns_ongoing_when_unanimous_reject` is the canary for this.

### `POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/shared-memories`

**Caller**: `app/routes/knowledge.py` (the knowledge-extract hook ingest path)

**Reads**:
| Path | Used in | Required |
|---|---|---|
| `response_id` | logged for audit | ✅ required |
| HTTP 201 status | success indicator | ✅ required |

**What we send**: openclaw-format records under `payload.metadata.format: "openclaw"`.
If CFN tightens validation here (renames `openclaw`, requires new fields), the hook
silently fails and CFN refuses ingestion.

## Request body contract — what we send

Equally important. If CFN renames a request field, our calls 4xx and the failure
modes are scattered across the codebase.

### /start request body
```json
{
  "session_id": "<unique per session>",
  "content_text": "<natural-language scenario for issue discovery>",
  "agents": [{"id": "<handle>", "name": "<handle>"}],
  "n_steps": 20
}
```
The CFN auto-compute formula runs when `n_steps` is omitted. Mycelium passes
`negotiation.n_steps` (default 20) explicitly; passing 0 in the body would cap
at zero rounds, so `cfn_negotiation.py:start_negotiation` omits the field when
`n_steps <= 0`.

### /decide request body
```json
{
  "session_id": "<must match /start>",
  "agent_replies": [
    {
      "agent_id": "<handle>",
      "participant_id": "<handle>",
      "action": "accept" | "reject" | "counter_offer",
      "offer": {"<issue>": "<option>", ...}   // when action == "counter_offer"
    }
  ]
}
```
**Critical:** `participant_id` is required. CFN's `BatchCallbackRunner` keys
reply lookup on this field; missing it breaks the batch (issue #105). Tested
indirectly via `test_decide_returns_ongoing_when_unanimous_reject`.

## Version history

| CFN version | Mycelium tested at | Date | Notes |
|---|---|---|---|
| 0.1.1 | (initial integration) | 2026-04-22 | Baseline contract |
| 0.1.2 | `feat/auto-config-docs` branch | 2026-04-28 | Build/deps-only release; no API surface changes verified by contract tests |

When CFN ships a new version:
1. `docker pull ghcr.io/outshift-open/ioc-cognition-fabric-node-svc:<new>`
2. Inspect the engines repo diff: `cd ~/Documents/GitHub/ioc-cfn-cognition-engines && git log v<old>..v<new>`
3. Bump compose.yml + run contract tests:
   ```bash
   docker compose ... up -d --force-recreate ioc-cognition-fabric-node-svc
   MYCELIUM_CFN_CONTRACT_TESTS=1 \
     WORKSPACE_ID=$(grep WORKSPACE_ID ~/.mycelium/.env | cut -d= -f2) \
     CFN_CONTRACT_MAS_ID=<a fresh MAS id> \
     uv run pytest fastapi-backend/tests/test_cfn_contract.py -v
   ```
4. If shape diverged: capture new fixtures in `fixtures/cfn/<new>/`, update this doc.
5. If shape held: append a row to the version history table.
