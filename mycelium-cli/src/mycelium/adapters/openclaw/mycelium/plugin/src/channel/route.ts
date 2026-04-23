// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * Pure routing logic for channel messages.
 *
 * routeMessage() inspects a Mycelium room message and returns a list of
 * actions the caller should execute. No side effects, no OpenClaw runtime
 * dependencies — just message inspection + policy decisions. This is the
 * layer that tests exercise directly.
 *
 * Side-effectful execution (actually dispatching agents, subscribing to SSE,
 * managing abort controllers) lives in channel/index.ts and calls routeMessage
 * to decide what to do.
 */

import type { ChannelConfig } from "../config.js";
import { resolveMentions } from "./mentions.js";

/** What the router decided should happen for a message. */
export type RouteAction =
  | {
      kind: "dispatch";
      agentId: string;
      sender: string;
      content: string;
      messageId: string | undefined;
    }
  | { kind: "subscribe-session"; roomName: string }
  | { kind: "ignore"; reason: string };

/**
 * Decide what to do with a message inbound from the room SSE stream.
 *
 * @param cfg              Channel configuration (agents, requireMention, etc.)
 * @param msg              Raw message object from the SSE stream
 * @param ownMessageIds    Set of message IDs we previously POSTed; used to skip
 *                         our own messages when they echo back through SSE.
 *                         Will have the matched ID deleted as a side effect
 *                         (caller passes a module-level set or a fresh test set).
 * @returns A list of actions the caller should execute in order.
 */
export function routeMessage(
  cfg: ChannelConfig,
  msg: any,
  ownMessageIds: Set<string>,
): RouteAction[] {
  // Skip messages we posted (loop prevention)
  if (msg.id && ownMessageIds.has(msg.id)) {
    ownMessageIds.delete(msg.id);
    return [{ kind: "ignore", reason: "own message" }];
  }
  if (msg.message_type === "announce") {
    return [{ kind: "ignore", reason: "announce" }];
  }

  if (msg.message_type === "coordination_tick") {
    return routeTick(cfg, msg);
  }
  if (msg.message_type === "coordination_consensus") {
    return routeConsensus(cfg, msg);
  }
  if (
    msg.message_type === "coordination_join" ||
    msg.message_type === "coordination_start"
  ) {
    return routeJoin(msg);
  }

  return routeBroadcast(cfg, msg);
}

// ── Tick ──────────────────────────────────────────────────────────────────

export function routeTick(cfg: ChannelConfig, msg: any): RouteAction[] {
  let tickData: any;
  try {
    tickData = typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
  } catch {
    return [{ kind: "ignore", reason: "tick parse error" }];
  }

  const payload = tickData?.payload ?? tickData;
  const targetAgent = payload?.participant_id;
  if (!targetAgent) {
    return [{ kind: "ignore", reason: "tick missing participant_id" }];
  }
  if (!cfg.agents.includes(targetAgent)) {
    return [{ kind: "ignore", reason: `tick participant_id ${targetAgent} not in channel agents` }];
  }

  const instruction = formatTickInstruction(payload, msg.room_name ?? cfg.room, targetAgent);

  return [
    {
      kind: "dispatch",
      agentId: targetAgent,
      sender: "CognitiveEngine",
      content: instruction,
      messageId: msg.id,
    },
  ];
}

export function formatTickInstruction(
  payload: any,
  roomName: string,
  targetAgent: string,
): string {
  const action = payload?.action ?? "respond";
  const canCounter = payload?.can_counter_offer === true;
  const currentOffer = payload?.current_offer ?? {};
  const round = payload?.round ?? "?";

  const offerSummary = Object.entries(currentOffer)
    .map(([k, v]) => `  ${k}: ${v}`)
    .join("\n");

  return [
    `[CognitiveEngine — Round ${round}]`,
    `You are in a structured negotiation in room ${roomName}.`,
    `Action required: ${action}`,
    canCounter
      ? "You CAN propose a counter-offer."
      : "You can only accept or reject.",
    "",
    "Current offer on the table:",
    offerSummary,
    "",
    canCounter
      ? `To counter-propose, run: mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... --room ${roomName} --handle ${targetAgent}`
      : "",
    `To accept: mycelium negotiate respond accept --room ${roomName} --handle ${targetAgent}`,
    `To reject: mycelium negotiate respond reject --room ${roomName} --handle ${targetAgent}`,
    "",
    "Explain your reasoning before running the command.",
  ]
    .filter(Boolean)
    .join("\n");
}

// ── Consensus ─────────────────────────────────────────────────────────────

export function routeConsensus(cfg: ChannelConfig, msg: any): RouteAction[] {
  let consensusData: any;
  try {
    consensusData =
      typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
  } catch {
    return [{ kind: "ignore", reason: "consensus parse error" }];
  }

  const summary = formatConsensusSummary(consensusData);

  return cfg.agents.map((agentId) => ({
    kind: "dispatch" as const,
    agentId,
    sender: "CognitiveEngine",
    content: summary,
    messageId: msg.id,
  }));
}

export function formatConsensusSummary(consensusData: any): string {
  const plan = consensusData?.plan ?? "No plan details";
  const assignments = consensusData?.assignments ?? {};
  const broken = consensusData?.broken === true;

  if (broken) {
    return `[CognitiveEngine — Negotiation FAILED]\n${plan}`;
  }
  return [
    "[CognitiveEngine — Consensus Reached!]",
    "",
    typeof plan === "string" ? plan : JSON.stringify(plan, null, 2),
    "",
    "Assignments:",
    ...Object.entries(assignments).map(([agent, task]) => `  ${agent}: ${task}`),
  ].join("\n");
}

// ── Join / session sub-room discovery ─────────────────────────────────────

export function routeJoin(msg: any): RouteAction[] {
  const roomName = msg.room_name;
  if (roomName && typeof roomName === "string" && roomName.includes(":session:")) {
    return [{ kind: "subscribe-session", roomName }];
  }
  return [{ kind: "ignore", reason: "join without session sub-room" }];
}

// ── Broadcast ─────────────────────────────────────────────────────────────

export function routeBroadcast(cfg: ChannelConfig, msg: any): RouteAction[] {
  const sender = msg.sender_handle ?? "unknown";
  const content = msg.content ?? "";
  if (!content.trim()) {
    return [{ kind: "ignore", reason: "empty content" }];
  }

  // Build the recipient list based on requireMention policy.
  let recipients: string[];
  if (cfg.requireMention) {
    const mentioned = resolveMentions(content, cfg.agents);
    recipients = mentioned.filter((agentId) => agentId !== sender);
    if (recipients.length === 0) {
      return [{ kind: "ignore", reason: "no addressed recipients (requireMention=true)" }];
    }
  } else {
    recipients = cfg.agents.filter((agentId) => agentId !== sender);
    if (recipients.length === 0) {
      return [{ kind: "ignore", reason: "no non-sender agents in broadcast mode" }];
    }
  }

  return recipients.map((agentId) => ({
    kind: "dispatch" as const,
    agentId,
    sender,
    content,
    messageId: msg.id,
  }));
}
