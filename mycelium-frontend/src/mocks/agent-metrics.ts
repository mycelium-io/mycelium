// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: what each agent costs the machine it runs on, as the runner would add
 * it to the machine report it already sends with every heartbeat.
 *
 * herdr names each pane's shell and its foreground processes, so an agent's
 * RAM is the sum over its pane's process tree: the agent CLI and whatever it
 * started, such as MCP servers. A subagent runs inside its parent's process,
 * so its memory is its parent's. An engine runs on the hub, and an agent on a
 * machine with no runner reports nothing.
 */

export interface AgentProcess {
  name: string;
  command: string;
  ramMb: number;
}

export interface AgentMetrics {
  handle: string;
  /** The agent CLI, as herdr names its kind. */
  kind: string;
  machine: string;
  state: "working" | "idle" | "blocked";
  ramMb: number;
  /** Percent of one core, averaged over the last minute. */
  cpu: number;
  up: string;
  processes: AgentProcess[];
  /** Subagents running inside this agent's process. */
  subagents?: { handle: string; state: "working" | "done" }[];
}

export interface MachineTotal {
  name: string;
  ramGb: number;
}

export const MACHINES: MachineTotal[] = [
  { name: "This computer", ramGb: 32 },
  { name: "morgan-mini", ramGb: 16 },
];

export const AGENT_METRICS: AgentMetrics[] = [
  {
    handle: "builder",
    kind: "claude",
    machine: "This computer",
    state: "working",
    ramMb: 1240,
    cpu: 34,
    up: "3h",
    processes: [
      { name: "claude", command: "claude --resume 4f1c…", ramMb: 812 },
      { name: "playwright-mcp", command: "npx @playwright/mcp", ramMb: 286 },
      { name: "github-mcp", command: "github-mcp-server stdio", ramMb: 98 },
      { name: "zsh", command: "-zsh", ramMb: 44 },
    ],
    subagents: [
      { handle: "builder:review", state: "working" },
      { handle: "builder:tests", state: "done" },
    ],
  },
  {
    handle: "reviewer",
    kind: "codex",
    machine: "morgan-mini",
    state: "idle",
    ramMb: 640,
    cpu: 1,
    up: "1d",
    processes: [
      { name: "codex", command: "codex resume", ramMb: 588 },
      { name: "zsh", command: "-zsh", ramMb: 52 },
    ],
  },
];

/** Members that report no metrics, and why. */
export const NO_METRICS: { handle: string; why: string }[] = [{ handle: "conductor", why: "Runs on the hub" }];

export const totalMb = AGENT_METRICS.reduce((s, a) => s + a.ramMb, 0);

/** "1.2 GB" or "640 MB". */
export function ram(mb: number): string {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

/** Whether the mock has metrics for this room. */
export function mockHasMetrics(room: string): boolean {
  return room === "checkout";
}
