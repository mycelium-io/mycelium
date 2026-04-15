// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Tests for the in-process knowledge ingest plugin shim (src/knowledge/ingest.ts).
 *
 * Regression coverage for issue #144: the plugin previously read the agent_id
 * via `getAgentId()`, which only returns `process.env.MYCELIUM_AGENT_ID`. For
 * channel-dispatched turns (where the gateway process owns the env and the
 * agentId lives on the OpenClaw context instead), the env var is empty, so
 * every ingest POST went out with `agent_id: undefined` and landed under
 * `(none)` in `mycelium cfn stats`. The fix prefers `ctx.agentId` and only
 * falls back to the env var.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the HTTP layer so we can observe outgoing POSTs without touching the
// network. The mock must be declared BEFORE the module under test is imported.
const apiPostMock = vi.fn().mockResolvedValue(true);
vi.mock("../src/http.js", () => ({
  apiPost: (...args: unknown[]) => apiPostMock(...args),
}));

// Mock the config layer so getWorkspaceId/getMasId return truthy sentinels and
// getAgentId returns the env-only value we control per-test.
const configMock = vi.hoisted(() => ({
  getWorkspaceId: vi.fn(() => "ws-1"),
  getMasId: vi.fn(() => "mas-1"),
  getAgentId: vi.fn(() => ""),
  resolveHandle: vi.fn((id?: string | null) => id ?? "unknown"),
}));
vi.mock("../src/config.js", () => configMock);

const { installKnowledgeIngest } = await import("../src/knowledge/ingest.js");

type Listener = (event: unknown, ctx: unknown) => Promise<void> | void;

function makeApi() {
  const listeners: Record<string, Listener> = {};
  return {
    api: {
      on: (name: string, fn: Listener) => {
        listeners[name] = fn;
      },
    },
    fire: (name: string, event: unknown, ctx: unknown) => listeners[name](event, ctx),
  };
}

const silentLog = { info: () => {}, warn: () => {} };

const longContent = "this is a response long enough to clear the 5 byte guard";

beforeEach(() => {
  apiPostMock.mockClear();
  configMock.getAgentId.mockReturnValue("");
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("installKnowledgeIngest — agent_id propagation (issue #144)", () => {
  it("uses ctx.agentId when the env var is empty (channel-dispatched turn)", async () => {
    const { api, fire } = makeApi();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    installKnowledgeIngest(api as any, null, silentLog);

    await fire(
      "message_sent",
      { to: "mycelium-room", content: longContent, success: true },
      { agentId: "exp-6967-agent-a" },
    );

    const ingestCall = apiPostMock.mock.calls.find(
      (c) => c[0] === "/api/knowledge/ingest",
    );
    expect(ingestCall).toBeDefined();
    expect(ingestCall?.[1].agent_id).toBe("exp-6967-agent-a");
  });

  it("falls back to getAgentId() when ctx has no agentId (direct openclaw agent invocation)", async () => {
    configMock.getAgentId.mockReturnValue("env-agent");
    const { api, fire } = makeApi();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    installKnowledgeIngest(api as any, null, silentLog);

    await fire(
      "message_sent",
      { to: "mycelium-room", content: longContent, success: true },
      {},
    );

    const ingestCall = apiPostMock.mock.calls.find(
      (c) => c[0] === "/api/knowledge/ingest",
    );
    expect(ingestCall?.[1].agent_id).toBe("env-agent");
  });

  it("prefers ctx.agentId over the env var when both are set", async () => {
    configMock.getAgentId.mockReturnValue("env-agent");
    const { api, fire } = makeApi();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    installKnowledgeIngest(api as any, null, silentLog);

    await fire(
      "message_sent",
      { to: "mycelium-room", content: longContent, success: true },
      { agentId: "ctx-agent" },
    );

    const ingestCall = apiPostMock.mock.calls.find(
      (c) => c[0] === "/api/knowledge/ingest",
    );
    expect(ingestCall?.[1].agent_id).toBe("ctx-agent");
  });

  it("sends undefined agent_id when neither ctx nor env have one (status-quo for unattributable turns)", async () => {
    const { api, fire } = makeApi();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    installKnowledgeIngest(api as any, null, silentLog);

    await fire(
      "message_sent",
      { to: "mycelium-room", content: longContent, success: true },
      {},
    );

    const ingestCall = apiPostMock.mock.calls.find(
      (c) => c[0] === "/api/knowledge/ingest",
    );
    expect(ingestCall?.[1].agent_id).toBeUndefined();
  });

  it("skips empty ctx.agentId strings and uses the env fallback", async () => {
    configMock.getAgentId.mockReturnValue("env-agent");
    const { api, fire } = makeApi();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    installKnowledgeIngest(api as any, null, silentLog);

    await fire(
      "message_sent",
      { to: "mycelium-room", content: longContent, success: true },
      { agentId: "   " },
    );

    const ingestCall = apiPostMock.mock.calls.find(
      (c) => c[0] === "/api/knowledge/ingest",
    );
    expect(ingestCall?.[1].agent_id).toBe("env-agent");
  });
});
