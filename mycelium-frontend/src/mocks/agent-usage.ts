// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The checkout room's agents on connected machines, as the hub lists them
 * (`GET /rooms/{room}/agents/running`): where each runs, its state, whether
 * it's kept running. No numbers: what an agent uses is read on its own machine
 * by the desktop app, never by the hub, so the mock app (a browser) has none.
 * Stop, start, pause and keep are held in memory so the Agents pane can be
 * driven. Agents owned by `operator` (the mock's person) can be acted on;
 * Morgan's can't, as on the hub.
 */

import type { AgentRunning } from "@/lib/api";

/** The runner the mock calls this computer, for a page that injects numbers. */
export const MOCK_HERE = "mock-runner-here";
const MINI = "mock-runner-mini";

function row(over: Partial<AgentRunning> & Pick<AgentRunning, "handle">): AgentRunning {
  return {
    room: "checkout",
    owner: "operator",
    state: "idle",
    kind: "claude",
    runner: MOCK_HERE,
    machine: "operator-mbp",
    pane: `w1:${over.handle}`,
    keep: false,
    restartable: false,
    ...over,
  };
}

function seed(): AgentRunning[] {
  return [
    row({ handle: "builder", state: "working", keep: true }),
    row({ handle: "research" }),
    row({ handle: "themes" }),
    row({ handle: "voice", state: "paused" }),
    row({ handle: "reviewer", owner: "morgan", kind: "codex", runner: MINI, machine: "morgan-mini" }),
    row({ handle: "refactorer", state: "stopped", restartable: true }),
  ];
}

const store = globalThis as { __myceliumMockRunning?: AgentRunning[] };

function running(): AgentRunning[] {
  return (store.__myceliumMockRunning ??= seed());
}

/** GET /rooms/{room}/agents/running. */
export function mockAgentsRunning(room: string): { agents: AgentRunning[] } {
  return { agents: room === "checkout" ? running() : [] };
}

/** POST /rooms/{room}/agents/{handle}/stop|start|pause|resume|keep for an agent
 *  the list has; `null` for one it doesn't, which the room's own mock answers. */
export function mockRunningControl(room: string, handle: string, verb: string, by: string, keep?: boolean): Response | null {
  const agent = room === "checkout" ? running().find((a) => a.handle === handle) : undefined;
  if (!agent) return null;
  if (agent.owner && agent.owner !== by) {
    return Response.json({ detail: `Only @${agent.owner}, who owns @${handle}, can pause, resume, stop, start or keep it.` }, { status: 403 });
  }
  if (verb === "stop") agent.state = "stopped";
  if (verb === "start") agent.state = "idle";
  if (verb === "pause" && agent.state !== "stopped") agent.state = "paused";
  if (verb === "resume" && agent.state === "paused") agent.state = "idle";
  if (verb === "keep") agent.keep = keep ?? true;
  return Response.json({ room, handle, paused: null, runner: agent.runner, job: "mock-job", keep: agent.keep });
}
