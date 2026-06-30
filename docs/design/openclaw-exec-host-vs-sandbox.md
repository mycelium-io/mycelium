# OpenClaw: `tools.exec.host=gateway` vs `sandbox.mode=off` for mycelium agents

Status: **active** — documents the fix introduced in `fix/openclaw-sandbox-exec-host`.

## Problem

Mycelium agents registered in OpenClaw need to run the `mycelium` CLI (e.g.
`mycelium negotiate respond accept`) in response to coordination ticks. When
an agent's sandbox is enabled, those `exec` calls silently fail — the mycelium
CLI is not installed inside the sandbox container, and the exec-approvals
allowlist that `mycelium agent add openclaw` writes is never consulted.

## Why sandbox mode breaks mycelium exec

Two separate mechanisms compound to cause the failure.

### 1. Process spawning — wrong host

`resolveExecTarget` in OpenClaw resolves the effective exec host at call time:

```typescript
// bash-tools.exec-runtime.ts
const effectiveHost =
  resolvedTarget === "auto"
    ? (params.sandboxAvailable ? "sandbox" : "gateway")
    : resolvedTarget;
```

When sandbox is enabled and `tools.exec.host` is unset (`auto`), every exec
call lands inside the sandbox container. The mycelium CLI is not installed
there — the command fails with "not found."

### 2. Allowlist skipped — wrong approval path

`mycelium agent add openclaw` writes approved mycelium commands into
`exec-approvals.json` via `_allowlist_mycelium()`. But OpenClaw only reads
that file for gateway-hosted execs:

```typescript
// bash-tools.exec.ts
const approvalPolicy =
  host === "sandbox"
    ? undefined                       // allowlist never loaded inside sandbox
    : resolveExecApprovalsFromFile({  // reads exec-approvals.json
        file: loadExecApprovals(),
        agentId, ...
      }).agent;
```

When exec is sandbox-hosted, `approvalPolicy = undefined` — the allowlist
entries written by `_allowlist_mycelium()` are silently bypassed regardless
of their content.

## The two fixes

Both fixes route `exec` to the gateway host (where mycelium is installed) and
restore the exec-approvals allowlist path. They differ in scope.

| | `sandbox.mode = 'off'` | `tools.exec.host = 'gateway'` |
|---|---|---|
| **How exec is routed** | `sandboxAvailable = false` → `auto` resolves to `gateway` | `configuredTarget = 'gateway'` → resolves directly, bypasses sandbox check |
| **Allowlist consulted?** | Yes — `host != "sandbox"` | Yes — `host != "sandbox"` |
| **Other tools (read/write/edit)** | Also run on host — no container isolation | Still run inside the sandbox container |
| **Blast radius** | All tools leave the sandbox | Only `exec` leaves the sandbox |

`tools.exec.host = 'gateway'` is the minimal correct fix: it routes only
`exec` to the host where mycelium lives and keeps all other tools (file reads,
writes, edits) inside the sandbox container.

## Example agent config (`openclaw.json`)

Both snippets show a single agent entry. Only the relevant keys are shown;
all other config is unchanged.

### Option A — disable sandbox entirely (simpler, less isolated)

```json
{
  "agents": {
    "list": [
      {
        "id": "lawyer-a",
        "name": "Lawyer A",
        "sandbox": {
          "mode": "off"
        }
      }
    ]
  }
}
```

### Option B — gateway exec only (recommended, preserves container isolation)

```json
{
  "agents": {
    "list": [
      {
        "id": "lawyer-a",
        "name": "Lawyer A",
        "tools": {
          "exec": {
            "host": "gateway"
          }
        }
      }
    ]
  }
}
```

With Option B, `read`, `write`, and `edit` still run inside the sandbox
container. Only `exec` is routed to the gateway host, which is exactly what
mycelium coordination requires.

## How mycelium sets this automatically

`mycelium agent add openclaw` (and `mycelium adapter add openclaw`) calls
`_configure_exec_host_gateway(agent_id)` in
`mycelium-cli/src/mycelium/integrations/openclaw/dispatch.py` immediately
after `_allowlist_mycelium()`. This writes `tools.exec.host = "gateway"` into
the agent's entry in `openclaw.json` so new agents are configured correctly
without manual intervention.

The `main` agent is an implicit OpenClaw default that never appears in
`agents.list` and therefore cannot be patched programmatically. If the `main`
session needs to run mycelium commands, use Option A for that agent or run
mycelium from a named agent instead.

## Verification

```bash
# Check effective sandbox config for a named agent
openclaw sandbox explain --agent lawyer-a

# Doctor checks both options and reports which agents can exec the mycelium CLI
mycelium doctor
```

`mycelium doctor` accepts either fix — it flags an agent only if both
`sandbox.mode` is not `off` AND `tools.exec.host` is not `gateway`.
