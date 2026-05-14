// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

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
  | { kind: "stash-return-address"; sessionRoom: string; agentId: string }
  | {
      kind: "stash-tick";
      sessionRoom: string;
      agentId: string;
      payload: any;
    }
  | {
      kind: "notify-home";
      sessionRoom: string;
      agentIds: string[];
      consensusSummary: string;
      messageId: string | undefined;
    }
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

  const actions: RouteAction[] = [];

  // Stash the agent's return address the first time we see a tick for them
  // in this session sub-room. The stash is idempotent on the executor side,
  // so emitting on every tick is fine — but only when room_name names a
  // session sub-room (not the parent room).
  const sessionRoom = msg.room_name ?? "";
  if (sessionRoom.includes(":session:")) {
    actions.push({
      kind: "stash-return-address",
      sessionRoom,
      agentId: targetAgent,
    });
    // Stash the raw tick payload so before_agent_start can inject it on the
    // agent's next turn — the dispatched instruction below is a terse human
    // summary that omits fields the agent needs (exact offer keys, valid_keys
    // on error ticks, etc.).
    actions.push({
      kind: "stash-tick",
      sessionRoom,
      agentId: targetAgent,
      payload,
    });
  }

  actions.push({
    kind: "dispatch",
    agentId: targetAgent,
    sender: "CognitiveEngine",
    content: instruction,
    messageId: msg.id,
  });

  return actions;
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
  const nStepsTotal = payload?.n_steps_total;
  const yourLastAction = payload?.your_last_action;
  const priorOutcome = payload?.prior_round_outcome;

  const offerSummary = Object.entries(currentOffer)
    .map(([k, v]) => `  ${k}: ${v}`)
    .join("\n");

  // Compose the round header. If we know the budget, surface remaining
  // rounds so the agent can decide whether to keep negotiating or walk
  // away with no agreement (a legitimate outcome — see SKILL.md).
  const roundHeader =
    typeof nStepsTotal === "number" && nStepsTotal > 0
      ? `[CognitiveEngine — Round ${round} of ${nStepsTotal}]`
      : `[CognitiveEngine — Round ${round}]`;

  // Prior-round context — eliminates the "this is my offer reflected back"
  // confusion by stating what just happened explicitly.
  const contextLines: string[] = [];
  if (priorOutcome && priorOutcome !== "first_round") {
    const outcomeText = priorOutcome.startsWith("rejected_by_")
      ? `Last round: ${priorOutcome.replace("rejected_by_", "")} rejected the standing offer.`
      : priorOutcome === "proposer_countered"
        ? "Last round: the designated proposer countered with a new offer (shown below)."
        : priorOutcome === "agreed"
          ? "Last round: all agents accepted."
          : `Last round: ${priorOutcome.replace(/_/g, " ")}.`;
    contextLines.push(outcomeText);
  }
  if (yourLastAction) {
    contextLines.push(`Your last action: ${yourLastAction}.`);
  }

  // Opt-in shared context files: any participant can attach files at join
  // time via `mycelium session join --context-files`. The CLI hashes them,
  // sends content to the backend, and the backend echoes the full content
  // here so every agent sees what was shared.
  const sharedContextFiles = Array.isArray(payload?.shared_context_files)
    ? payload.shared_context_files
    : [];
  const contextFilesBlock: string[] = [];
  if (sharedContextFiles.length > 0) {
    contextFilesBlock.push("Shared context files (opt-in by participants):");
    for (const cf of sharedContextFiles) {
      const path = cf?.path ?? "(unknown)";
      const sharer = cf?.shared_by ?? "?";
      const content = cf?.content ?? "";
      contextFilesBlock.push(`--- ${path} (shared by ${sharer}) ---`);
      contextFilesBlock.push(content);
      contextFilesBlock.push("--- end ---");
    }
  }

  return [
    roundHeader,
    `You are in a structured negotiation in room ${roomName}.`,
    `Action required: ${action}`,
    canCounter
      ? "You CAN propose a counter-offer."
      : "You can only accept or reject.",
    ...(contextLines.length > 0 ? ["", ...contextLines] : []),
    ...(contextFilesBlock.length > 0 ? ["", ...contextFilesBlock] : []),
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
    "Explain your reasoning before running the command. Walking away with no agreement is a legitimate outcome — keep rejecting until the session ends if your hard constraints can't be met.",
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

  const actions: RouteAction[] = cfg.agents.map((agentId) => ({
    kind: "dispatch" as const,
    agentId,
    sender: "CognitiveEngine",
    content: summary,
    messageId: msg.id,
  }));

  // Also notify each agent's home channel session (Matrix/Discord/etc.)
  // with the consensus summary. The notify-home executor checks whether a
  // return address was stashed for each (session, agent) pair when the agent
  // first showed up in the negotiation; agents without a stash are skipped.
  // Passing all of cfg.agents is safe — the per-agent stash check is the
  // real filter — and avoids fragile inference of who participated from
  // assignment keys (which can be issue names rather than agent IDs).
  const sessionRoom = msg.room_name ?? "";
  if (cfg.agents.length > 0 && sessionRoom.includes(":session:")) {
    actions.push({
      kind: "notify-home",
      sessionRoom,
      agentIds: cfg.agents,
      consensusSummary: summary,
      messageId: msg.id,
    });
  }

  return actions;
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
  if (!(roomName && typeof roomName === "string" && roomName.includes(":session:"))) {
    return [{ kind: "ignore", reason: "join without session sub-room" }];
  }
  const actions: RouteAction[] = [{ kind: "subscribe-session", roomName }];

  // Stash the return address for the joining agent so we can deliver
  // consensus back to their home channel later. coordination_join carries
  // the joiner's handle in sender_handle; coordination_start does not
  // (it's CFN-broadcast for the whole session).
  const sender =
    msg.message_type === "coordination_join" ? msg.sender_handle : undefined;
  if (sender && typeof sender === "string") {
    actions.push({
      kind: "stash-return-address",
      sessionRoom: roomName,
      agentId: sender,
    });
  }
  return actions;
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
