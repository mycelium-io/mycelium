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
  /** `paused`: in memory with its wakes held. `stopped`: its process ended to
   *  free memory, its pane and conversation kept for Start. */
  state: "working" | "idle" | "blocked" | "paused" | "stopped";
  /** How long since its last turn, for picking agents to stop. */
  idleFor?: string;
  /** Kept running when agents are stopped in bulk. */
  keep?: boolean;
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
    keep: true,
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
    idleFor: "40m",
    processes: [
      { name: "codex", command: "codex resume", ramMb: 588 },
      { name: "zsh", command: "-zsh", ramMb: 52 },
    ],
  },
  {
    handle: "research",
    kind: "claude",
    machine: "This computer",
    state: "idle",
    idleFor: "5h",
    ramMb: 980,
    cpu: 0,
    up: "2d",
    processes: [
      { name: "claude", command: "claude --resume 9a2e…", ramMb: 702 },
      { name: "browser-mcp", command: "npx @browsermcp/mcp", ramMb: 236 },
      { name: "zsh", command: "-zsh", ramMb: 42 },
    ],
  },
  {
    handle: "themes",
    kind: "claude",
    machine: "This computer",
    state: "idle",
    idleFor: "3h",
    ramMb: 760,
    cpu: 0,
    up: "1d",
    processes: [
      { name: "claude", command: "claude --resume 1b7d…", ramMb: 718 },
      { name: "zsh", command: "-zsh", ramMb: 42 },
    ],
  },
  {
    handle: "voice",
    kind: "claude",
    machine: "This computer",
    state: "paused",
    idleFor: "1h",
    ramMb: 690,
    cpu: 0,
    up: "6h",
    processes: [
      { name: "claude", command: "claude --resume 7c40…", ramMb: 650 },
      { name: "zsh", command: "-zsh", ramMb: 40 },
    ],
  },
  {
    handle: "refactorer",
    kind: "claude",
    machine: "This computer",
    state: "stopped",
    idleFor: "1d",
    ramMb: 0,
    cpu: 0,
    up: "",
    processes: [],
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
