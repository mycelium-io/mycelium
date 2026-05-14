// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Tests for routeMessage — the pure routing logic that decides what to do
 * with each inbound message. This is the highest-value test in the plugin:
 * cascade bugs, mention bugs, tick participant_id filter bugs all live here.
 */

import { describe, expect, it } from "vitest";
import type { ChannelConfig } from "../src/config.js";
import {
  formatConsensusSummary,
  formatTickInstruction,
  routeMessage,
} from "../src/channel/route.js";

const baseCfg: ChannelConfig = {
  backendUrl: "http://localhost:8001",
  room: "test-room",
  agents: ["julia-agent", "selina-agent", "arnold"],
  requireMention: true,
};

const freshOwnIds = () => new Set<string>();

// ── Own message / loop prevention ─────────────────────────────────────────

describe("routeMessage — loop prevention", () => {
  it("ignores a message whose id is in ownMessageIds", () => {
    const ownIds = new Set(["msg-123"]);
    const actions = routeMessage(
      baseCfg,
      {
        id: "msg-123",
        message_type: "broadcast",
        sender_handle: "julia-agent",
        content: "@selina-agent ping",
      },
      ownIds,
    );
    expect(actions).toEqual([{ kind: "ignore", reason: "own message" }]);
  });

  it("deletes the matched id from ownMessageIds (one-shot match)", () => {
    const ownIds = new Set(["msg-123"]);
    routeMessage(baseCfg, { id: "msg-123", message_type: "broadcast" }, ownIds);
    expect(ownIds.has("msg-123")).toBe(false);
  });

  it("does not ignore a message whose id is NOT in ownMessageIds", () => {
    const actions = routeMessage(
      baseCfg,
      {
        id: "msg-456",
        message_type: "broadcast",
        sender_handle: "human",
        content: "@julia-agent ping",
      },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("dispatch");
  });
});

// ── Announce ──────────────────────────────────────────────────────────────

describe("routeMessage — announce", () => {
  it("ignores announce messages", () => {
    const actions = routeMessage(
      baseCfg,
      { message_type: "announce", content: "agent offline" },
      freshOwnIds(),
    );
    expect(actions).toEqual([{ kind: "ignore", reason: "announce" }]);
  });
});

// ── Broadcast (requireMention=true) ───────────────────────────────────────

describe("routeMessage — broadcast, requireMention=true", () => {
  it("ignores a broadcast with no @mentions", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "broadcast",
        sender_handle: "facilitator",
        content: "hey anyone around",
      },
      freshOwnIds(),
    );
    expect(actions).toHaveLength(1);
    expect(actions[0].kind).toBe("ignore");
    if (actions[0].kind === "ignore") {
      expect(actions[0].reason).toContain("requireMention");
    }
  });

  it("ignores a broadcast with empty content", () => {
    const actions = routeMessage(
      baseCfg,
      { message_type: "broadcast", sender_handle: "human", content: "" },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });

  it("dispatches to a single addressed agent", () => {
    const actions = routeMessage(
      baseCfg,
      {
        id: "abc",
        message_type: "broadcast",
        sender_handle: "human",
        content: "@julia-agent ping",
      },
      freshOwnIds(),
    );
    expect(actions).toHaveLength(1);
    expect(actions[0]).toMatchObject({
      kind: "dispatch",
      agentId: "julia-agent",
      sender: "human",
      content: "@julia-agent ping",
      messageId: "abc",
    });
  });

  it("dispatches to multiple addressed agents in one broadcast", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "broadcast",
        sender_handle: "human",
        content: "@julia-agent and @selina-agent please sync",
      },
      freshOwnIds(),
    );
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId);
    expect(dispatchedAgents).toEqual(["julia-agent", "selina-agent"]);
  });

  it("does not dispatch an agent's message back to themselves", () => {
    // julia-agent mentioning herself should be a no-op for her (she wouldn't
    // reply to her own message), though she can still mention others
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "broadcast",
        sender_handle: "julia-agent",
        content: "@julia-agent reminder @selina-agent thoughts?",
      },
      freshOwnIds(),
    );
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId);
    expect(dispatchedAgents).toEqual(["selina-agent"]);
  });

  it("ignores a broadcast that only mentions the sender themselves", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "broadcast",
        sender_handle: "julia-agent",
        content: "@julia-agent internal note",
      },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });

  it("ignores mentions of agents not in the channel", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "broadcast",
        sender_handle: "human",
        content: "@random-bot please help",
      },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });
});

// ── Broadcast (requireMention=false) ──────────────────────────────────────

describe("routeMessage — broadcast, requireMention=false", () => {
  const broadcastCfg: ChannelConfig = { ...baseCfg, requireMention: false };

  it("dispatches an un-mentioned broadcast to all non-sender agents", () => {
    const actions = routeMessage(
      broadcastCfg,
      {
        message_type: "broadcast",
        sender_handle: "human",
        content: "hey everyone",
      },
      freshOwnIds(),
    );
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId)
      .sort();
    expect(dispatchedAgents).toEqual(["arnold", "julia-agent", "selina-agent"]);
  });

  it("excludes the sender from broadcast dispatches", () => {
    const actions = routeMessage(
      broadcastCfg,
      {
        message_type: "broadcast",
        sender_handle: "julia-agent",
        content: "hey team",
      },
      freshOwnIds(),
    );
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId)
      .sort();
    expect(dispatchedAgents).toEqual(["arnold", "selina-agent"]);
  });

  it("ignores a broadcast when the only agent is also the sender", () => {
    const soloCfg: ChannelConfig = { ...broadcastCfg, agents: ["julia-agent"] };
    const actions = routeMessage(
      soloCfg,
      { message_type: "broadcast", sender_handle: "julia-agent", content: "note to self" },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });
});

// ── Coordination tick ─────────────────────────────────────────────────────

describe("routeMessage — coordination_tick", () => {
  const tickMsg = (participantId: string, extra: Record<string, unknown> = {}) => ({
    id: "tick-1",
    message_type: "coordination_tick",
    room_name: "test-room:session:abc123",
    content: JSON.stringify({
      payload: {
        participant_id: participantId,
        round: 3,
        action: "respond",
        can_counter_offer: false,
        current_offer: { price: "500", timeline: "30 days" },
        ...extra,
      },
    }),
  });

  it("dispatches to the addressed participant only", () => {
    const actions = routeMessage(baseCfg, tickMsg("julia-agent"), freshOwnIds());
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId);
    expect(dispatchedAgents).toEqual(["julia-agent"]);
  });

  it("ignores ticks for participants not in the channel agents list", () => {
    const actions = routeMessage(baseCfg, tickMsg("stranger-bot"), freshOwnIds());
    expect(actions).toHaveLength(1);
    expect(actions[0].kind).toBe("ignore");
  });

  it("ignores ticks with no participant_id", () => {
    const msg = {
      id: "tick-2",
      message_type: "coordination_tick",
      content: JSON.stringify({ payload: { round: 3, action: "respond" } }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions[0].kind).toBe("ignore");
  });

  it("dispatches with CognitiveEngine as sender", () => {
    const actions = routeMessage(baseCfg, tickMsg("julia-agent"), freshOwnIds());
    const dispatch = actions.find((a) => a.kind === "dispatch") as any;
    expect(dispatch).toMatchObject({ kind: "dispatch", sender: "CognitiveEngine" });
  });

  it("passes through the tick's own message id (for echo prevention)", () => {
    const actions = routeMessage(baseCfg, tickMsg("julia-agent"), freshOwnIds());
    const dispatch = actions.find((a) => a.kind === "dispatch") as any;
    expect(dispatch.messageId).toBe("tick-1");
  });

  it("emits stash-return-address alongside dispatch when room_name names a session sub-room", () => {
    const actions = routeMessage(baseCfg, tickMsg("julia-agent"), freshOwnIds());
    const stash = actions.find((a) => a.kind === "stash-return-address") as any;
    expect(stash).toEqual({
      kind: "stash-return-address",
      sessionRoom: "test-room:session:abc123",
      agentId: "julia-agent",
    });
  });

  it("does NOT emit stash-return-address when the tick has no session sub-room name", () => {
    const msg = {
      id: "rootless-tick",
      message_type: "coordination_tick",
      content: JSON.stringify({ payload: { participant_id: "julia-agent", round: 1, action: "respond", current_offer: {} } }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions.some((a) => a.kind === "stash-return-address")).toBe(false);
  });

  it("emits stash-tick carrying the raw tick payload so session/before_agent_start can inject it", () => {
    const actions = routeMessage(baseCfg, tickMsg("julia-agent"), freshOwnIds());
    const stash = actions.find((a) => a.kind === "stash-tick") as any;
    expect(stash).toBeDefined();
    expect(stash).toMatchObject({
      kind: "stash-tick",
      sessionRoom: "test-room:session:abc123",
      agentId: "julia-agent",
    });
    // payload must include the fields the agent needs that aren't in the
    // dispatched human-readable summary (exact offer keys, can_counter_offer).
    expect(stash.payload).toMatchObject({
      participant_id: "julia-agent",
      round: 3,
      current_offer: { price: "500", timeline: "30 days" },
    });
  });

  it("does NOT emit stash-tick when the tick has no session sub-room name", () => {
    const msg = {
      id: "rootless-tick",
      message_type: "coordination_tick",
      content: JSON.stringify({ payload: { participant_id: "julia-agent", round: 1, action: "respond", current_offer: {} } }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions.some((a) => a.kind === "stash-tick")).toBe(false);
  });

  it("ignores ticks with unparseable content", () => {
    const msg = {
      message_type: "coordination_tick",
      content: "{this is not json",
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions[0].kind).toBe("ignore");
  });

  it("ignores participants that are NOT in this channel's agents list even if they look valid", () => {
    // This is the fairness guarantee: one room has many potential agents;
    // this plugin instance is only bound to cfg.agents. Ticks for other agents
    // must not leak into our dispatch.
    const cfg2: ChannelConfig = { ...baseCfg, agents: ["julia-agent"] };
    const actions = routeMessage(cfg2, tickMsg("selina-agent"), freshOwnIds());
    expect(actions[0].kind).toBe("ignore");
  });

  it("supports the legacy top-level participant_id format", () => {
    // Some CFN versions emit participant_id at the top level of content, not under payload
    const msg = {
      id: "tick-legacy",
      message_type: "coordination_tick",
      content: JSON.stringify({
        participant_id: "julia-agent",
        round: 1,
        action: "propose",
      }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions[0]).toMatchObject({ kind: "dispatch", agentId: "julia-agent" });
  });
});

// ── Coordination consensus ────────────────────────────────────────────────

describe("routeMessage — coordination_consensus", () => {
  const consensusMsg = (broken = false) => ({
    id: "consensus-1",
    message_type: "coordination_consensus",
    room_name: "test-room:session:abc123",
    content: JSON.stringify({
      plan: "Ship v1 with core features only",
      assignments: { "julia-agent": "build API", "selina-agent": "ship frontend" },
      broken,
    }),
  });

  it("dispatches consensus to all channel agents", () => {
    const actions = routeMessage(baseCfg, consensusMsg(), freshOwnIds());
    const dispatchedAgents = actions
      .filter((a) => a.kind === "dispatch")
      .map((a) => (a as any).agentId)
      .sort();
    expect(dispatchedAgents).toEqual(["arnold", "julia-agent", "selina-agent"]);
  });

  it("dispatches with CognitiveEngine as sender", () => {
    const actions = routeMessage(baseCfg, consensusMsg(), freshOwnIds());
    for (const action of actions) {
      if (action.kind === "dispatch") {
        expect(action.sender).toBe("CognitiveEngine");
      }
    }
  });

  it("ignores consensus with unparseable content", () => {
    const msg = {
      message_type: "coordination_consensus",
      content: "{broken",
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions[0].kind).toBe("ignore");
  });

  it("emits a notify-home action with all cfg.agents and the session room", () => {
    const actions = routeMessage(baseCfg, consensusMsg(), freshOwnIds());
    const notify = actions.find((a) => a.kind === "notify-home") as any;
    expect(notify).toBeDefined();
    expect(notify.sessionRoom).toBe("test-room:session:abc123");
    expect(notify.agentIds.sort()).toEqual(["arnold", "julia-agent", "selina-agent"]);
    expect(notify.consensusSummary).toContain("Ship v1");
    expect(notify.messageId).toBe("consensus-1");
  });

  it("emits notify-home for broken/timeout consensus too", () => {
    const msg = {
      id: "broken-consensus",
      message_type: "coordination_consensus",
      room_name: "test-room:session:xyz",
      content: JSON.stringify({
        plan: "Negotiation ended: timeout",
        assignments: {},
        broken: true,
      }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    const notify = actions.find((a) => a.kind === "notify-home") as any;
    expect(notify).toBeDefined();
    expect(notify.agentIds.sort()).toEqual(["arnold", "julia-agent", "selina-agent"]);
    expect(notify.consensusSummary).toContain("Negotiation FAILED");
  });

  it("emits notify-home with cfg.agents even when assignments are keyed by issue names", () => {
    // Real-world case: CFN sometimes emits assignments keyed by issue name,
    // not agent ID. The previous filter dropped everything; passing cfg.agents
    // through unconditionally is the simpler, correct behavior.
    const msg = {
      id: "issue-keyed-consensus",
      message_type: "coordination_consensus",
      room_name: "test-room:session:abc",
      content: JSON.stringify({
        plan: "REST + OpenAPI as default",
        assignments: {
          "REST + OpenAPI is the right default": "REST + OpenAPI with graduated adoption",
        },
        broken: false,
      }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    const notify = actions.find((a) => a.kind === "notify-home") as any;
    expect(notify).toBeDefined();
    expect(notify.agentIds.sort()).toEqual(["arnold", "julia-agent", "selina-agent"]);
  });

  it("does NOT emit notify-home when the consensus message has no session room_name", () => {
    const msg = {
      id: "rootless-consensus",
      message_type: "coordination_consensus",
      content: JSON.stringify({ plan: "X", assignments: { "julia-agent": "y" }, broken: false }),
    };
    const actions = routeMessage(baseCfg, msg, freshOwnIds());
    expect(actions.some((a) => a.kind === "notify-home")).toBe(false);
  });
});

// ── Coordination join (session sub-room discovery) ────────────────────────

describe("routeMessage — coordination_join", () => {
  it("returns subscribe-session action for messages with :session: in room_name", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "coordination_join",
        room_name: "test-room:session:abc123",
      },
      freshOwnIds(),
    );
    expect(actions[0]).toEqual({
      kind: "subscribe-session",
      roomName: "test-room:session:abc123",
    });
  });

  it("emits stash-return-address when coordination_join has a sender_handle", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "coordination_join",
        room_name: "test-room:session:abc123",
        sender_handle: "julia-agent",
      },
      freshOwnIds(),
    );
    const stash = actions.find((a) => a.kind === "stash-return-address") as any;
    expect(stash).toBeDefined();
    expect(stash.sessionRoom).toBe("test-room:session:abc123");
    expect(stash.agentId).toBe("julia-agent");
  });

  it("does NOT emit stash-return-address for coordination_start (no per-agent sender)", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "coordination_start",
        room_name: "test-room:session:xyz",
        sender_handle: "CognitiveEngine",
      },
      freshOwnIds(),
    );
    expect(actions.some((a) => a.kind === "stash-return-address")).toBe(false);
  });

  it("handles coordination_start the same as coordination_join (subscribe only)", () => {
    const actions = routeMessage(
      baseCfg,
      {
        message_type: "coordination_start",
        room_name: "test-room:session:xyz",
      },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("subscribe-session");
  });

  it("ignores join messages without a session sub-room name", () => {
    const actions = routeMessage(
      baseCfg,
      { message_type: "coordination_join", room_name: "test-room" },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });

  it("ignores join messages with no room_name at all", () => {
    const actions = routeMessage(
      baseCfg,
      { message_type: "coordination_join" },
      freshOwnIds(),
    );
    expect(actions[0].kind).toBe("ignore");
  });
});

// ── Tick instruction formatting ───────────────────────────────────────────

describe("formatTickInstruction", () => {
  it("includes the round number and action", () => {
    const instruction = formatTickInstruction(
      { round: 5, action: "propose", can_counter_offer: true, current_offer: {} },
      "my-room",
      "julia-agent",
    );
    expect(instruction).toContain("Round 5");
    expect(instruction).toContain("propose");
  });

  it("includes the room name and handle in the CLI commands", () => {
    const instruction = formatTickInstruction(
      { round: 1, action: "respond" },
      "api-debate",
      "julia-agent",
    );
    expect(instruction).toContain("--room api-debate");
    expect(instruction).toContain("--handle julia-agent");
  });

  it("shows the propose command when can_counter_offer is true", () => {
    const instruction = formatTickInstruction(
      { round: 1, action: "propose", can_counter_offer: true },
      "r",
      "a",
    );
    expect(instruction).toContain("mycelium negotiate propose");
  });

  it("omits the propose command when can_counter_offer is false", () => {
    const instruction = formatTickInstruction(
      { round: 1, action: "respond", can_counter_offer: false },
      "r",
      "a",
    );
    expect(instruction).not.toContain("mycelium negotiate propose");
  });

  it("lists current offer fields in the body", () => {
    const instruction = formatTickInstruction(
      {
        round: 1,
        current_offer: { price: "500k", timeline: "30 days" },
      },
      "r",
      "a",
    );
    expect(instruction).toContain("price: 500k");
    expect(instruction).toContain("timeline: 30 days");
  });

  it("renders shared context files when present", () => {
    const instruction = formatTickInstruction(
      {
        round: 1,
        action: "respond",
        current_offer: {},
        shared_context_files: [
          {
            shared_by: "alpha",
            path: "/agents/alpha/SOUL.md",
            sha256: "deadbeef",
            content: "I value privacy and clarity.",
          },
        ],
      },
      "r",
      "alpha",
    );
    expect(instruction).toContain("Shared context files");
    expect(instruction).toContain("/agents/alpha/SOUL.md");
    expect(instruction).toContain("shared by alpha");
    expect(instruction).toContain("I value privacy and clarity.");
  });

  it("omits the shared context block when empty", () => {
    const instruction = formatTickInstruction(
      { round: 1, action: "respond", current_offer: {}, shared_context_files: [] },
      "r",
      "a",
    );
    expect(instruction).not.toContain("Shared context files");
  });
});

// ── Consensus summary formatting ──────────────────────────────────────────

describe("formatConsensusSummary", () => {
  it("formats a successful consensus with assignments", () => {
    const summary = formatConsensusSummary({
      plan: "ship it",
      assignments: { julia: "code", selina: "ship" },
      broken: false,
    });
    expect(summary).toContain("Consensus Reached");
    expect(summary).toContain("ship it");
    expect(summary).toContain("julia: code");
    expect(summary).toContain("selina: ship");
  });

  it("formats a broken negotiation", () => {
    const summary = formatConsensusSummary({
      plan: "could not converge after 20 rounds",
      assignments: {},
      broken: true,
    });
    expect(summary).toContain("Negotiation FAILED");
    expect(summary).toContain("could not converge");
  });

  it("handles missing fields gracefully", () => {
    const summary = formatConsensusSummary({});
    expect(summary).toContain("No plan details");
  });

  it("stringifies object-shaped plans", () => {
    const summary = formatConsensusSummary({
      plan: { decision: "REST", migration: "later" },
      assignments: {},
    });
    expect(summary).toContain("REST");
    expect(summary).toContain("migration");
  });
});
