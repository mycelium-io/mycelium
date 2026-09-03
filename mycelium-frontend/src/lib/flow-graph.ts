// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * An episode's interaction flow, laid out to be drawn.
 *
 * The flow is a small graph the conductor walks: steps in the order they were
 * written, edges as `next`, a branch as one edge per stance. This lays it out
 * in declaration order — steps are declared in the order they are meant to
 * run, so the order is the rank — and marks an edge that points back up the
 * line as a loop. A short flow reads left to right; a longer one stands as a
 * column, since the pane that shows it is narrow and a row of eleven boxes
 * would either scroll away or shrink to nothing. Pure: no DOM, no layout
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
  w: number;
}

export interface FlowEdge {
  from: string;
  to: string;
  /** The stances that take this edge, joined, or null for a plain edge. */
  label: string | null;
  /** Points back to an earlier step: a loop. */
  back: boolean;
  /**
   * The lane this edge rides in when it leaves the line of nodes: a loop
   * under the row, or a loop (left) or a skip (right) beside the column.
   * Null for an edge between neighbours, drawn straight.
   */
  rail: number | null;
}

export type FlowDirection = "row" | "column";

export interface FlowLayout {
  direction: FlowDirection;
  nodes: FlowNode[];
  edges: FlowEdge[];
  width: number;
  height: number;
}

export const NODE_W = 132;
export const NODE_H = 46;
export const GAP_X = 56;
export const PAD = 24;
/** Room under a row before the first loop, and per loop after it: each loop
 *  gets a lane of its own so two never share a line or a label. */
export const LOOP_BASE = 16;
export const LANE_GAP = 14;
/** A flow with this many steps or more stands as a column. Three boxes fit
 *  the thread pane side by side; four do not. */
export const COLUMN_AT = 4;
/** A column's boxes are wider — there is room, and a group step's cast is long. */
export const COLUMN_NODE_W = 224;
export const GAP_Y = 30;

/** Who a step is put to, in the flow's own words. */
export function stepWho(step: FlowStep, flow: EpisodeFlow): string | null {
  const to = step.to;
  if (!to) return null;
  const bound = flow.bound ?? {};
  if (to in bound) return bound[to];
  const cast = flow.cast ?? [];
  if (to === "each" || to === "all") return cast.length ? cast.join(", ") : "everyone";
  if (to === "workers") {
    const named = new Set(Object.values(bound));
    const workers = cast.filter((h) => !named.has(h));
    return workers.length ? workers.join(", ") : "the workers";
  }
  return to;
}

function stepWhat(step: FlowStep): string {
  if (step.end) return `ends ${step.end}`;
  const verb = step.wait === "none" ? "tells" : "asks";
  const rounds = step.rounds && step.rounds > 1 ? ` ×${step.rounds}` : "";
  return `${verb} ${step.to ?? "?"}${rounds}`;
}

/** The edges a flow declares, one per (from, to), with the stances that take
 *  it joined into one label — `reject / default` is one arrow, not two. */
function flowEdges(steps: FlowStep[]): Omit<FlowEdge, "rail">[] {
  const index = new Map(steps.map((s, i) => [s.id, i]));
  const edges: Omit<FlowEdge, "rail">[] = [];
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
      const seen = edges.find((e) => e.from === step.id && e.to === to);
      if (seen) {
        if (label) seen.label = seen.label ? `${seen.label} / ${label}` : label;
        continue;
      }
      edges.push({ from: step.id, to, label, back: (index.get(to) ?? 0) <= from });
    }
  }
  return edges;
}

export function layoutFlow(flow: EpisodeFlow): FlowLayout {
  const steps = flow.steps ?? [];
  const index = new Map(steps.map((s, i) => [s.id, i]));
  const direction: FlowDirection = steps.length >= COLUMN_AT ? "column" : "row";
  const bare = flowEdges(steps);
  const describe = (step: FlowStep) => ({
    id: step.id,
    what: stepWhat(step),
    who: stepWho(step, flow),
    end: step.end ?? null,
  });

  if (direction === "row") {
    // Loops ride under the row, each in its own lane.
    let loops = 0;
    const edges: FlowEdge[] = bare.map((e) => ({ ...e, rail: e.back ? loops++ : null }));
    const nodes: FlowNode[] = steps.map((step, i) => ({
      ...describe(step),
      x: PAD + i * (NODE_W + GAP_X),
      y: PAD,
      w: NODE_W,
    }));
    return {
      direction,
      nodes,
      edges,
      width: PAD * 2 + steps.length * NODE_W + Math.max(0, steps.length - 1) * GAP_X,
      height: PAD * 2 + NODE_H + (loops ? LOOP_BASE + loops * LANE_GAP : 0),
    };
  }

  // A column: neighbours join straight down; a loop rides a rail on the
  // left, a skip over one or more steps a rail on the right.
  let left = 0;
  let right = 0;
  const edges: FlowEdge[] = bare.map((e) => {
    if (e.back) return { ...e, rail: left++ };
    const span = (index.get(e.to) ?? 0) - (index.get(e.from) ?? 0);
    return { ...e, rail: span > 1 ? right++ : null };
  });
  const x = PAD + left * LANE_GAP;
  const nodes: FlowNode[] = steps.map((step, i) => ({
    ...describe(step),
    x,
    y: PAD + i * (NODE_H + GAP_Y),
    w: COLUMN_NODE_W,
  }));
  return {
    direction,
    nodes,
    edges,
    width: PAD * 2 + left * LANE_GAP + COLUMN_NODE_W + right * LANE_GAP,
    height: PAD * 2 + steps.length * NODE_H + Math.max(0, steps.length - 1) * GAP_Y,
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
