// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Where an agent's terminal is, from what the hub already knows: which of your
// machines reports it, and its herdr pane there. Only ids; what the terminal
// shows is read on the machine itself (`useAgentScreen`), never from the hub.

import type { MachineAgent, Runner } from "@/lib/api";

export type AgentPlace =
  /** On this machine, in herdr pane `pane`. */
  | {
      kind: "here";
      runner: Runner;
      pane: string;
      state: MachineAgent["state"] | null;
    }
  /** On another of your machines. */
  | { kind: "yours"; runner: Runner }
  /** On someone else's machine, which isn't yours to look at. */
  | { kind: "theirs" }
  /** In no terminal Mycelium can see: started by hand, or not running. */
  | { kind: "unseen" };

/**
 * Where @`handle` of `room` runs. `thisMachine` is the runner id of the machine
 * this page is on (the desktop app says), and `runnerOf` the machine its
 * manifest names, if any.
 */
export function placeOf(
  runners: Runner[],
  thisMachine: string | null,
  room: string,
  handle: string,
  runnerOf?: string | null,
): AgentPlace {
  for (const runner of runners) {
    const reported = runner.machine?.workspaces
      .flatMap((w) => w.agents)
      .find((a) => a.room === room && a.handle === handle);
    const started = runner.agents.find((a) => a.room === room && a.handle === handle);
    const pane = reported?.pane ?? started?.pane ?? null;
    if (!pane) continue;
    if (runner.id === thisMachine) return { kind: "here", runner, pane, state: reported?.state ?? null };
    return { kind: "yours", runner };
  }
  return runnerOf ? { kind: "theirs" } : { kind: "unseen" };
}
