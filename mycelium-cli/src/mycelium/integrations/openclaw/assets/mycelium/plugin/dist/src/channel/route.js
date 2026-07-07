// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
import { resolveMentions } from "./mentions.js";
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
export function routeMessage(cfg, msg, ownMessageIds) {
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
    if (msg.message_type === "coordination_join" ||
        msg.message_type === "coordination_start") {
        return routeJoin(msg);
    }
    return routeBroadcast(cfg, msg);
}
// ── Tick ──────────────────────────────────────────────────────────────────
export function routeTick(cfg, msg) {
    let tickData;
    try {
        tickData = typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
    }
    catch {
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
    const instruction = formatTickInstruction(tickData, msg.room_name ?? cfg.room, targetAgent);
    const actions = [];
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
export function formatTickInstruction(tickData, roomName, targetAgent) {
    // Two tick shapes from the backend:
    //  - normal tick: { payload: { round, action, current_offer, ... } }
    //  - error tick:  { error, valid_keys, bad_keys, instruction, payload: { participant_id } }
    // formatTickInstruction must render BOTH completely — it is the agent's sole
    // source of tick information per CLAUDE.md. Don't strip fields that the
    // agent needs for recovery (e.g. valid_keys on counter_offer_invalid_keys).
    const errorKind = typeof tickData?.error === "string" ? tickData.error : undefined;
    if (errorKind) {
        return formatErrorTick(tickData, roomName, targetAgent);
    }
    const payload = tickData?.payload ?? tickData;
    const action = payload?.action ?? "respond";
    const canCounter = payload?.can_counter_offer === true;
    const currentOffer = payload?.current_offer ?? {};
    const round = payload?.round ?? "?";
    const nStepsTotal = payload?.n_steps_total;
    const yourLastAction = payload?.your_last_action;
    const priorOutcome = payload?.prior_round_outcome;
    const offerKeys = Object.keys(currentOffer);
    const offerSummary = Object.entries(currentOffer)
        .map(([k, v]) => `  ${k}: ${v}`)
        .join("\n");
    // Compose the round header. If we know the budget, surface remaining
    // rounds so the agent can decide whether to keep negotiating or walk
    // away with no agreement (a legitimate outcome — see SKILL.md).
    const roundHeader = typeof nStepsTotal === "number" && nStepsTotal > 0
        ? `[CognitiveEngine — Round ${round} of ${nStepsTotal}]`
        : `[CognitiveEngine — Round ${round}]`;
    // Prior-round context — eliminates the "this is my offer reflected back"
    // confusion by stating what just happened explicitly.
    const contextLines = [];
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
    const contextFilesBlock = [];
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
    // Team prior: the team's earned confidence on this topic from previous
    // negotiations (with a provenance weight). Rendered so the agent can weigh
    // it, after forming its own position first.
    const teamPrior = payload?.team_prior;
    const priorConfidence = typeof teamPrior?.confidence === "number" ? teamPrior.confidence : undefined;
    const priorBlock = [];
    if (priorConfidence !== undefined) {
        const qualifiers = [];
        if (typeof teamPrior?.provenance_weight === "number") {
            qualifiers.push(`provenance weight ${teamPrior.provenance_weight.toFixed(2)}`);
        }
        if (typeof teamPrior?.episode_count === "number") {
            qualifiers.push(`from ${teamPrior.episode_count} prior episode${teamPrior.episode_count === 1 ? "" : "s"}`);
        }
        const qualifierText = qualifiers.length > 0 ? ` (${qualifiers.join(", ")})` : "";
        priorBlock.push(`Team prior on this topic: ${priorConfidence.toFixed(2)}${qualifierText}. Form your own position first, then weigh this.`);
    }
    // Open plan tasks: the parent room's `plan/` namespace contains the active
    // todo list. Surfaced here so agents weigh their proposals against work that
    // is already committed.
    const planOpenTasks = typeof payload?.plan_open_tasks === "string" ? payload.plan_open_tasks : "";
    const planBlock = [];
    if (planOpenTasks) {
        planBlock.push(planOpenTasks);
    }
    // Valid offer keys: when composing a counter-offer the agent MUST use these
    // exact keys (case + spacing). Strict enumeration here closes the gap that
    // used to drive the parallel prependContext injection (#276 / #285).
    const validKeysLine = canCounter && offerKeys.length > 0
        ? `Valid offer keys (use exactly these in your counter): ${offerKeys.map((k) => `"${k}"`).join(", ")}`
        : "";
    return [
        roundHeader,
        `You are in a structured negotiation in room ${roomName}.`,
        `Action required: ${action}`,
        canCounter
            ? "You CAN propose a counter-offer."
            : "You can only accept or reject.",
        ...(contextLines.length > 0 ? ["", ...contextLines] : []),
        ...(contextFilesBlock.length > 0 ? ["", ...contextFilesBlock] : []),
        ...(priorBlock.length > 0 ? ["", ...priorBlock] : []),
        ...(planBlock.length > 0 ? ["", ...planBlock] : []),
        "",
        "Current offer on the table:",
        offerSummary,
        "",
        validKeysLine,
        canCounter
            ? `To counter-propose, run: mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... --room ${roomName} --handle ${targetAgent}`
            : "",
        `To accept: mycelium negotiate respond accept --room ${roomName} --handle ${targetAgent}`,
        `To reject: mycelium negotiate respond reject --room ${roomName} --handle ${targetAgent}`,
        "",
        "Include `--confidence <0-1>` in your reply, and optionally `--evidence <path-or-claim>` (repeatable) and `--reasoning <why>` to cite what your position rests on. If you accept only by deference (yielding without being persuaded), add `--defer-to <handle>`; that honesty is measured, not punished.",
        "",
        "Explain your reasoning before running the command. Walking away with no agreement is a legitimate outcome — keep rejecting until the session ends if your hard constraints can't be met.",
    ]
        .filter(Boolean)
        .join("\n");
}
/**
 * Render an error tick (e.g. ``counter_offer_invalid_keys``,
 * ``counter_offer_not_your_turn``). The backend posts these as a
 * ``coordination_tick`` with top-level ``error`` / ``instruction`` /
 * ``valid_keys`` / ``bad_keys`` fields (see services/coordination.py
 * around line 1298). The agent needs ALL of this to recover — especially
 * ``valid_keys`` for the invalid-keys case — so we render it explicitly here
 * rather than letting the agent guess.
 */
export function formatErrorTick(tickData, roomName, targetAgent) {
    const errorKind = String(tickData?.error ?? "unknown_error");
    const instruction = String(tickData?.instruction ?? "");
    const validKeys = Array.isArray(tickData?.valid_keys) ? tickData.valid_keys : [];
    const badKeys = Array.isArray(tickData?.bad_keys) ? tickData.bad_keys : [];
    const lines = [
        `[CognitiveEngine — error: ${errorKind}]`,
        `Room: ${roomName}`,
    ];
    if (instruction)
        lines.push("", instruction);
    if (badKeys.length > 0) {
        lines.push("", `Rejected keys: ${badKeys.map((k) => `"${k}"`).join(", ")}`);
    }
    if (validKeys.length > 0) {
        lines.push("", `Valid keys (use exactly these): ${validKeys.map((k) => `"${k}"`).join(", ")}`);
    }
    // Recovery command — concrete next step. Most error ticks are recoverable
    // by re-submitting a counter-offer with the correct keys.
    if (errorKind === "counter_offer_invalid_keys" && validKeys.length > 0) {
        const example = validKeys.map((k) => `"${k}"=VALUE`).join(" ");
        lines.push("", `Recovery: mycelium negotiate propose ${example} --room ${roomName} --handle ${targetAgent}`);
    }
    else if (errorKind === "counter_offer_not_your_turn") {
        lines.push("", `Recovery: mycelium negotiate respond accept --room ${roomName} --handle ${targetAgent}`, `      or: mycelium negotiate respond reject --room ${roomName} --handle ${targetAgent}`);
    }
    return lines.join("\n");
}
// ── Consensus ─────────────────────────────────────────────────────────────
export function routeConsensus(cfg, msg) {
    let consensusData;
    try {
        consensusData =
            typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
    }
    catch {
        return [{ kind: "ignore", reason: "consensus parse error" }];
    }
    const summary = formatConsensusSummary(consensusData);
    const actions = cfg.agents.map((agentId) => ({
        kind: "dispatch",
        agentId,
        sender: "CognitiveEngine",
        content: summary,
        messageId: msg.id,
    }));
    // Also notify each agent's home channel session (the Mycelium room, or an external channel)
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
export function formatConsensusSummary(consensusData) {
    const plan = consensusData?.plan ?? "No plan details";
    const assignments = consensusData?.assignments ?? {};
    const broken = consensusData?.broken === true;
    const planFile = typeof consensusData?.plan_file === "string" ? consensusData.plan_file : "";
    if (broken) {
        return `[CognitiveEngine — Negotiation FAILED]\n${plan}`;
    }
    // Consensus quality metrics (when the backend computed them):
    //   MPC = mean final confidence, GAR = genuine agreement ratio,
    //   SCR = social compliance ratio (fraction of accepts that were deferred).
    // Guard every field: older backends omit metrics entirely.
    const metrics = consensusData?.metrics;
    const metricParts = [];
    if (typeof metrics?.mpc === "number")
        metricParts.push(`MPC ${metrics.mpc.toFixed(2)}`);
    if (typeof metrics?.gar === "number")
        metricParts.push(`GAR ${metrics.gar.toFixed(2)}`);
    if (typeof metrics?.scr === "number")
        metricParts.push(`SCR ${metrics.scr.toFixed(2)}`);
    const qualityLine = metricParts.length > 0 ? `Quality: ${metricParts.join(" · ")}` : "";
    const cfnPersisted = consensusData?.cfn_persisted === true;
    return [
        "[CognitiveEngine — Consensus Reached!]",
        "",
        typeof plan === "string" ? plan : JSON.stringify(plan, null, 2),
        "",
        "Assignments:",
        ...Object.entries(assignments).map(([agent, task]) => `  ${agent}: ${task}`),
        ...(qualityLine
            ? [
                "",
                qualityLine,
                "(MPC = mean final confidence; GAR = fraction of agents genuinely persuaded; SCR = fraction of accepts made by deference.)",
            ]
            : []),
        ...(cfnPersisted ? ["", "This agreement was persisted to CFN shared memory."] : []),
        // The consensus has been compiled into the room's shared plan. Point the
        // agent at it so the negotiation flows straight into doing the work.
        ...(planFile
            ? [
                "",
                `The consensus is now the room's shared plan (\`${planFile}\`).`,
                "Run `mycelium plan tasks` to see the checklist, work your tasks, and",
                "tick them off with `mycelium plan task done <id>`.",
            ]
            : []),
    ].join("\n");
}
// ── Join / session sub-room discovery ─────────────────────────────────────
export function routeJoin(msg) {
    const roomName = msg.room_name;
    if (!(roomName && typeof roomName === "string" && roomName.includes(":session:"))) {
        return [{ kind: "ignore", reason: "join without session sub-room" }];
    }
    const actions = [{ kind: "subscribe-session", roomName }];
    // Stash the return address for the joining agent so we can deliver
    // consensus back to their home channel later. coordination_join carries
    // the joiner's handle in sender_handle; coordination_start does not
    // (it's CFN-broadcast for the whole session).
    const sender = msg.message_type === "coordination_join" ? msg.sender_handle : undefined;
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
export function routeBroadcast(cfg, msg) {
    const sender = msg.sender_handle ?? "unknown";
    const content = msg.content ?? "";
    if (!content.trim()) {
        return [{ kind: "ignore", reason: "empty content" }];
    }
    // Build the recipient list based on requireMention policy.
    let recipients;
    if (cfg.requireMention) {
        const mentioned = resolveMentions(content, cfg.agents);
        recipients = mentioned.filter((agentId) => agentId !== sender);
        if (recipients.length === 0) {
            return [{ kind: "ignore", reason: "no addressed recipients (requireMention=true)" }];
        }
    }
    else {
        recipients = cfg.agents.filter((agentId) => agentId !== sender);
        if (recipients.length === 0) {
            return [{ kind: "ignore", reason: "no non-sender agents in broadcast mode" }];
        }
    }
    return recipients.map((agentId) => ({
        kind: "dispatch",
        agentId,
        sender,
        content,
        messageId: msg.id,
    }));
}
