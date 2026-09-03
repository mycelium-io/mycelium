// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * An episode's interaction flow, laid out to be drawn.
 *
 * The flow is a small graph the conductor walks: steps in the order they were
 * written, edges as `next`, a branch as one edge per stance. This lays it out
 * left to right in declaration order — steps are declared in the order they
 * are meant to run, so the order is the rank — and marks an edge that points
 * back up the line as a loop, drawn under the row. Pure: no DOM, no layout
 * library, so it is testable and the drawing is one pass over its output.
 */

import type { EpisodeFlow, FlowStep, FlowTraceEntry } from "./api";

export interface FlowNode {
  id: string;
  /** What the step does, as a person reads it: "asks guardian", "ends resolved". */
  what: string;
  /** The member bound to the step's role, when the flow says who. */
  who: string | null;
  end: "resolved" | "rejected" | null;
  x: number;
  y: number;
}

export interface FlowEdge {
  from: string;
  to: string;
  /** The stance that takes this edge, or null for a plain edge. */
  label: string | null;
  /** Points back to an earlier step: a loop, drawn below the row. */
  back: boolean;
}

export interface FlowLayout {
  nodes: FlowNode[];
  edges: FlowEdge[];
  width: number;
  height: number;
}

export const NODE_W = 132;
export const NODE_H = 46;
export const GAP_X = 56;
export const PAD = 24;
/** Room under the row for loop edges. */
export const LOOP_H = 52;

/** Who a step is put to, in the flow's own words. */
export function stepWho(step: FlowStep, flow: EpisodeFlow): string | null {
  const to = step.to;
  if (!to) return null;
  const bound = flow.bound ?? {};
  if (to in bound) return bound[to];
  if (to === "each" || to === "all") return "everyone";
  if (to === "workers") return "the workers";
  return to;
}

function stepWhat(step: FlowStep): string {
  if (step.end) return `ends ${step.end}`;
  const verb = step.wait === "none" ? "tells" : "asks";
  const rounds = step.rounds && step.rounds > 1 ? ` ×${step.rounds}` : "";
  return `${verb} ${step.to ?? "?"}${rounds}`;
}

export function layoutFlow(flow: EpisodeFlow): FlowLayout {
  const steps = flow.steps ?? [];
  const index = new Map(steps.map((s, i) => [s.id, i]));
  const nodes: FlowNode[] = steps.map((step, i) => ({
    id: step.id,
    what: stepWhat(step),
    who: stepWho(step, flow),
    end: step.end ?? null,
    x: PAD + i * (NODE_W + GAP_X),
    y: PAD,
  }));
  const edges: FlowEdge[] = [];
  for (const step of steps) {
    const from = index.get(step.id) ?? 0;
    const targets: [string, string | null][] =
      typeof step.next === "string"
        ? [[step.next, null]]
        : step.next
          ? Object.entries(step.next).map(([stance, to]) => [to, stance])
          : [];
    for (const [to, label] of targets) {
      if (!index.has(to)) continue;
      edges.push({ from: step.id, to, label, back: (index.get(to) ?? 0) <= from });
    }
  }
  const hasLoop = edges.some((e) => e.back);
  return {
    nodes,
    edges,
    width: PAD * 2 + Math.max(0, steps.length) * NODE_W + Math.max(0, steps.length - 1) * GAP_X,
    height: PAD * 2 + NODE_H + (hasLoop ? LOOP_H : 0),
  };
}

export type StepState = "current" | "visited" | "reached" | "untouched";

/**
 * What each step is to the run right now: the one it stands at, the ones it
 * has taken, the end it reached, or nothing yet.
 */
export function stepStates(
  flow: EpisodeFlow,
  trace: FlowTraceEntry[],
  currentStep: string | null | undefined,
  outcome: string,
): Map<string, StepState> {
  const states = new Map<string, StepState>();
  for (const step of flow.steps ?? []) states.set(step.id, "untouched");
  for (const entry of trace) if (states.has(entry.step)) states.set(entry.step, "visited");
  if (outcome !== "open") {
    // A finished run reached the end step its last edge led to, or ended at
    // the cap on the step it stood at.
    const last = trace[trace.length - 1];
    const reached = last ? last.next : null;
    if (reached && states.has(reached)) {
      const end = (flow.steps ?? []).find((s) => s.id === reached)?.end;
      states.set(reached, end ? "reached" : "visited");
    }
  } else if (currentStep && states.has(currentStep)) {
    states.set(currentStep, "current");
  }
  return states;
}

/** The edges the run actually took, as "from→to" keys, so they draw solid. */
export function takenEdges(trace: FlowTraceEntry[]): Set<string> {
  return new Set(trace.map((t) => `${t.step}→${t.next}`));
}
