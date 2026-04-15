// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Tests for the mycelium-knowledge-extract hook's pure helpers.
 *
 * Regression coverage for issue #144: when a `message:sent` event arrives
 * from a channel-dispatched turn, `event.context.agentId` is missing and
 * the handler must fall back to the agentId parsed from the sessionKey.
 * Before the fix, `ingestToMycelium` re-read agentId from env vars only,
 * so every channel-dispatched ingest landed under agent `(none)` in
 * `mycelium cfn stats`.
 *
 * The knowledge-env module pulls a config file that only exists at install
 * time (`../../extensions/mycelium/read-mycelium-config.js`), so we mock it
 * here — the functions under test are pure and never actually read config.
 */

import { describe, expect, it, vi } from "vitest";

vi.mock(
  "../../hooks/mycelium-knowledge-extract/knowledge-env.js",
  () => ({
    getIngestConfig: () => ({
      enabled: true,
      events: ["message:sent", "agent:bootstrap"],
      maxToolContentBytes: 4096,
      skipInProgressTurn: true,
    }),
    getIngestTarget: () => ({
      apiUrl: "http://localhost:8001",
      workspaceId: "ws-1",
      masId: "mas-1",
      agentId: null,
    }),
  }),
);

const {
  buildIngestBody,
  resolveSessionMeta,
  resolveAgentSession,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} = (await import(
  "../../hooks/mycelium-knowledge-extract/handler.js"
)) as any;

// ── buildIngestBody: agent_id precedence ─────────────────────────────────────

describe("buildIngestBody — agent_id precedence", () => {
  const payload = { schema: "openclaw-conversation-v1", turns: [] };
  const baseTarget = {
    apiUrl: "http://localhost:8001",
    workspaceId: "ws-1",
    masId: "mas-1",
    agentId: null,
  };

  it("uses the resolved agent_id when present (issue #144 fix)", () => {
    const body = buildIngestBody(baseTarget, "exp-6967-agent-a", payload);
    expect(body.agent_id).toBe("exp-6967-agent-a");
  });

  it("falls back to target.agentId when resolved is null", () => {
    const target = { ...baseTarget, agentId: "env-agent" };
    const body = buildIngestBody(target, null, payload);
    expect(body.agent_id).toBe("env-agent");
  });

  it("prefers resolved over target even when target has an env value", () => {
    const target = { ...baseTarget, agentId: "env-agent" };
    const body = buildIngestBody(target, "resolved-agent", payload);
    expect(body.agent_id).toBe("resolved-agent");
  });

  it("returns null when neither resolved nor target provides an agent_id", () => {
    const body = buildIngestBody(baseTarget, null, payload);
    expect(body.agent_id).toBeNull();
  });

  it("treats undefined resolved as null", () => {
    const target = { ...baseTarget, agentId: "fallback" };
    const body = buildIngestBody(target, undefined, payload);
    expect(body.agent_id).toBe("fallback");
  });

  it("wraps payload in records array and echoes workspace/mas ids", () => {
    const body = buildIngestBody(baseTarget, "a", payload);
    expect(body.workspace_id).toBe("ws-1");
    expect(body.mas_id).toBe("mas-1");
    expect(body.records).toEqual([payload]);
  });
});

// ── resolveSessionMeta: ctx vs resolved precedence ───────────────────────────

describe("resolveSessionMeta — resolved fallback", () => {
  it("uses resolved agentId/sessionId when ctx is empty (channel-dispatched turn)", () => {
    const event = {
      type: "message",
      action: "sent",
      context: {},
      sessionKey: "agent:exp-6967-agent-a:mycelium-room:group:room-1",
    };
    const meta = resolveSessionMeta(event, [], {
      agentId: "exp-6967-agent-a",
      sessionId: "sess-abc",
    });
    expect(meta.agentId).toBe("exp-6967-agent-a");
    expect(meta.sessionId).toBe("sess-abc");
    expect(meta.sessionKey).toBe("agent:exp-6967-agent-a:mycelium-room:group:room-1");
    // channelFromKey strips the `agent:{agentId}:` prefix and takes the first segment
    expect(meta.channel).toBe("mycelium-room");
  });

  it("prefers ctx values when both ctx and resolved are supplied (matches pre-fix direct path)", () => {
    const event = {
      type: "message",
      action: "sent",
      context: { agentId: "ctx-agent", sessionId: "ctx-sess" },
      sessionKey: "agent:ctx-agent:direct:main",
    };
    // Handler always passes `resolved`, but ctx wins when the handler's
    // resolver short-circuited on ctx.
    const meta = resolveSessionMeta(event, [], {
      agentId: "ctx-agent",
      sessionId: "ctx-sess",
    });
    expect(meta.agentId).toBe("ctx-agent");
    expect(meta.sessionId).toBe("ctx-sess");
    expect(meta.channel).toBe("direct");
  });

  it("falls through to ctx when resolved is omitted entirely", () => {
    const event = {
      type: "message",
      action: "sent",
      context: { agentId: "ctx-only", sessionId: "ctx-sess" },
      sessionKey: "agent:ctx-only:direct:main",
    };
    const meta = resolveSessionMeta(event, []);
    expect(meta.agentId).toBe("ctx-only");
    expect(meta.sessionId).toBe("ctx-sess");
  });

  it("returns null channel when the session key cannot be parsed (no agentId)", () => {
    const event = { type: "message", action: "sent", context: {}, sessionKey: "" };
    const meta = resolveSessionMeta(event, [], { agentId: null, sessionId: null });
    expect(meta.agentId).toBeNull();
    expect(meta.sessionId).toBeNull();
    expect(meta.channel).toBeNull();
  });

  it("picks up cwd from a session entry", () => {
    const event = {
      type: "message",
      action: "sent",
      context: {},
      sessionKey: "agent:a:mycelium-room:group:r",
    };
    const entries = [{ type: "session", cwd: "/tmp/project" }];
    const meta = resolveSessionMeta(event, entries, { agentId: "a", sessionId: "s" });
    expect(meta.cwd).toBe("/tmp/project");
  });
});

// ── resolveAgentSession: sessionKey fallback path ────────────────────────────

describe("resolveAgentSession — ctx short-circuit", () => {
  it("returns ctx.agentId / ctx.sessionId directly when both are present", () => {
    const event = {
      context: { agentId: "exp-3959-agent-a", sessionId: "uuid-1" },
      sessionKey: "agent:exp-3959-agent-a:direct:main",
    };
    expect(resolveAgentSession(event)).toEqual({
      agentId: "exp-3959-agent-a",
      sessionId: "uuid-1",
    });
  });

  it("returns null when sessionKey is missing the agent prefix", () => {
    const event = { context: {}, sessionKey: "channel:discord:something" };
    expect(resolveAgentSession(event)).toBeNull();
  });

  it("returns null when sessionKey is empty", () => {
    const event = { context: {}, sessionKey: "" };
    expect(resolveAgentSession(event)).toBeNull();
  });
});
