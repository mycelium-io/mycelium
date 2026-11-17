// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What the checkout room's agents use, as their machines' runners would report
 * it (`GET /rooms/{room}/agents/usage`), with stop, start and keep held in
 * memory so the Agents pane can be driven. Made-up numbers; only checkout has
 * any. Agents owned by `operator` (the mock's person) can be acted on; Morgan's
 * can't, as on the hub.
 */

import type { AgentUsage, AgentsUsage } from "@/lib/api";

const HERE = "mock-runner-here";
const MINI = "mock-runner-mini";
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const claude = (session: string, mb: number) => ({ name: "claude", command: `claude --resume ${session}`, ram_mb: mb });
const zsh = (mb: number) => ({ name: "zsh", command: "-zsh", ram_mb: mb });

function row(over: Partial<AgentUsage> & Pick<AgentUsage, "handle">): AgentUsage {
  return {
    room: "checkout",
    owner: "operator",
    state: "idle",
    kind: "claude",
    runner: HERE,
    machine: "This computer",
    pane: `w1:${over.handle}`,
    keep: false,
    ram_mb: 0,
    cpu: 0,
    up_s: 3600,
    idle_since: null,
    processes: [],
    subagents_open: null,
    restartable: false,
    ...over,
  };
}

function seed(): AgentsUsage {
  return {
    machines: [
      { runner: HERE, machine: "This computer", ram_total_mb: 32768 },
      { runner: MINI, machine: "morgan-mini", ram_total_mb: 16384 },
    ],
    agents: [
      row({
        handle: "builder",
        state: "working",
        keep: true,
        ram_mb: 1240,
        cpu: 34,
        up_s: 3 * 3600,
        processes: [
          claude("4f1c…", 812),
          { name: "playwright-mcp", command: "npx @playwright/mcp", ram_mb: 286 },
          { name: "github-mcp", command: "github-mcp-server stdio", ram_mb: 98 },
          zsh(44),
        ],
        subagents_open: 2,
      }),
      row({ handle: "research", idle_since: ago(5 * 60), ram_mb: 980, processes: [claude("9a2e…", 702), zsh(42)] }),
      row({ handle: "themes", idle_since: ago(3 * 60), ram_mb: 760, processes: [claude("1b7d…", 718), zsh(42)] }),
      row({ handle: "voice", state: "paused", idle_since: ago(70), ram_mb: 690, processes: [claude("7c40…", 650), zsh(40)] }),
      row({
        handle: "reviewer",
        owner: "morgan",
        kind: "codex",
        runner: MINI,
        machine: "morgan-mini",
        idle_since: ago(40),
        ram_mb: 640,
        cpu: 1,
        processes: [{ name: "codex", command: "codex resume", ram_mb: 588 }, zsh(52)],
      }),
      row({ handle: "refactorer", state: "stopped", idle_since: ago(26 * 60), ram_mb: null, cpu: null, restartable: true }),
    ],
  };
}

const store = globalThis as { __myceliumMockUsage?: AgentsUsage };

function usage(): AgentsUsage {
  return (store.__myceliumMockUsage ??= seed());
}

/** GET /rooms/{room}/agents/usage. */
export function mockAgentsUsage(room: string): AgentsUsage {
  if (room !== "checkout") return { machines: [], agents: [] };
  const all = usage();
  return { machines: all.machines, agents: [...all.agents].sort((a, b) => (b.ram_mb ?? 0) - (a.ram_mb ?? 0)) };
}

/** POST /rooms/{room}/agents/{handle}/stop|start|pause|resume|keep for an agent
 *  the usage has; `null` for one it doesn't, which the room's own mock answers. */
export function mockUsageControl(room: string, handle: string, verb: string, by: string, keep?: boolean): Response | null {
  const agent = room === "checkout" ? usage().agents.find((a) => a.handle === handle) : undefined;
  if (!agent) return null;
  if (agent.owner && agent.owner !== by) {
    return Response.json({ detail: `Only @${agent.owner}, who owns @${handle}, can pause, resume, stop, start or keep it.` }, { status: 403 });
  }
  if (verb === "stop") Object.assign(agent, { state: "stopped", ram_mb: null, cpu: null, processes: [] });
  if (verb === "start") Object.assign(agent, { state: "idle", idle_since: new Date().toISOString(), ram_mb: 640, cpu: 0 });
  if (verb === "pause" && agent.state !== "stopped") agent.state = "paused";
  if (verb === "resume" && agent.state === "paused") agent.state = "idle";
  if (verb === "keep") agent.keep = keep ?? true;
  return Response.json({ room, handle, paused: null, runner: agent.runner, job: "mock-job", keep: agent.keep });
}
