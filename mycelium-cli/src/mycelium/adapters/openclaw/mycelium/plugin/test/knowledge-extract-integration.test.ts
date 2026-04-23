// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * End-to-end wiring test for the mycelium-knowledge-extract HookHandler.
 *
 * The pure-helper tests in knowledge-extract-handler.test.ts verify that
 * buildIngestBody and resolveSessionMeta apply the correct agent_id
 * precedence in isolation. What they don't catch is whether the
 * HookHandler default export actually threads agentId from
 * resolveAgentSession into the ingestToMycelium call site — a bad merge
 * could re-break that wiring and every unit test would still pass.
 *
 * This test exercises the full path: mock the HTTP transport and
 * filesystem, fire a channel-dispatched event (empty ctx, agentId only
 * in the sessionKey), and assert that the resulting POST body carries
 * the sessionKey-parsed agentId. Issue #144 regression guard.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks (hoisted above the dynamic import) ─────────────────────────────────

vi.mock("../../hooks/mycelium-knowledge-extract/knowledge-env.js", () => ({
  getIngestConfig: () => ({
    enabled: true,
    events: ["message:sent"],
    maxToolContentBytes: 4096,
    skipInProgressTurn: true,
  }),
  getIngestTarget: () => ({
    apiUrl: "http://localhost:8001",
    workspaceId: "ws-1",
    masId: "mas-1",
    // env agent is null — simulates the pre-fix environment where the
    // gateway process doesn't know the per-turn agent identity. The whole
    // point of the #144 fix is that the handler must NOT fall back to this
    // when the sessionKey carries a real agentId.
    agentId: null,
  }),
}));

const postKnowledgeIngestMock = vi.fn().mockResolvedValue(true);
vi.mock("../../hooks/mycelium-knowledge-extract/knowledge-http.js", () => ({
  postKnowledgeIngest: (...args: unknown[]) => postKnowledgeIngestMock(...args),
}));

// handler.js uses `import fs from "fs"` + `import fsPromises from "fs/promises"`,
// so each mock must provide BOTH a `default` export and named members.

const SESSIONS_INDEX = {
  "agent:exp-channel-agent:mycelium-room:group:room-1": {
    sessionId: "sess-xyz",
  },
};

const SESSION_JSONL = [
  {
    type: "message",
    timestamp: "2026-04-15T00:00:00Z",
    message: { role: "user", content: "hello" },
  },
  {
    type: "message",
    message: {
      role: "assistant",
      content: [{ type: "text", text: "world" }],
    },
  },
]
  .map((e) => JSON.stringify(e))
  .join("\n");

vi.mock("fs", () => {
  const readFileSync = vi.fn((p: string) => {
    const s = String(p);
    if (s.endsWith("sessions.json")) {
      return JSON.stringify(SESSIONS_INDEX);
    }
    // Delta state read — simulate "never sent" so lastSentIndex = -1.
    const err = new Error("ENOENT") as NodeJS.ErrnoException;
    err.code = "ENOENT";
    throw err;
  });
  const mkdirSync = vi.fn();
  const writeFileSync = vi.fn();
  const appendFileSync = vi.fn();
  const api = { readFileSync, mkdirSync, writeFileSync, appendFileSync };
  return { default: api, ...api };
});

vi.mock("fs/promises", () => {
  const readFile = vi.fn(async (p: string) => {
    const s = String(p);
    if (s.endsWith("sess-xyz.jsonl")) return SESSION_JSONL;
    const err = new Error("ENOENT") as NodeJS.ErrnoException;
    err.code = "ENOENT";
    throw err;
  });
  const api = { readFile };
  return { default: api, ...api };
});

// Dynamic import must come after vi.mock() declarations.
const { default: HookHandler } = (await import(
  "../../hooks/mycelium-knowledge-extract/handler.js"
)) as { default: (event: unknown) => Promise<void> };

async function flushDetachedIngest(): Promise<void> {
  // HookHandler fires ingestToMycelium as a detached `.then().catch().finally()`
  // chain and returns immediately. Awaiting the handler isn't enough — the
  // POST lands on a microtask that runs after the handler resolves. 10ms is
  // plenty for the mocked transport to settle.
  await new Promise((r) => setTimeout(r, 10));
}

describe("HookHandler — end-to-end agentId wiring (issue #144)", () => {
  beforeEach(() => {
    postKnowledgeIngestMock.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("threads agentId parsed from sessionKey into the ingest POST body", async () => {
    const event = {
      type: "message",
      action: "sent",
      // Channel-dispatched turn: the openclaw gateway does not populate
      // ctx.agentId here because the gateway process owns the env, not
      // the agent. The agentId only exists in the sessionKey.
      context: {},
      sessionKey: "agent:exp-channel-agent:mycelium-room:group:room-1",
    };

    await HookHandler(event);
    await flushDetachedIngest();

    expect(postKnowledgeIngestMock).toHaveBeenCalledOnce();
    // postKnowledgeIngest(apiUrl, body)
    const body = postKnowledgeIngestMock.mock.calls[0][1] as {
      agent_id: string;
      workspace_id: string;
      mas_id: string;
      records: unknown[];
    };
    expect(body.agent_id).toBe("exp-channel-agent");
    expect(body.workspace_id).toBe("ws-1");
    expect(body.mas_id).toBe("mas-1");
    expect(body.records).toHaveLength(1);
  });
});
