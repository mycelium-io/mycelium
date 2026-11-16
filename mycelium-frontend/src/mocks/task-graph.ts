// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: a task's graph, as the hub would work it out on read from what it
 * already stores: the task's parts (`part-of`) and their `depends-on`, each
 * part's pull request, the asks in its thread and their answers, conductor
 * runs and what they saved (`context/decision`, `context/summary`), and an
 * agent's subagents, branching off the step they worked on.
 *
 * Nodes marked `note` are step 2: steps an agent labels itself (`tried`,
 * `found`, `ruled out`, `blocked by`), which nothing stores yet.
 */

export type GraphKind =
  | "task"
  | "part"
  | "pr"
  | "ask"
  | "answer"
  | "run"
  | "decision"
  | "summary"
  | "subagent"
  | "post"
  | "tried"
  | "found"
  | "ruled-out"
  | "blocked";

export type GraphState = "done" | "working" | "open" | "blocked" | "waiting" | "dropped";

export interface GraphNode {
  id: string;
  kind: GraphKind;
  label: string;
  /** A quiet second word on the node: a PR's state, when a subagent ended. */
  meta?: string;
  /** A subagent's handle, for its tooltip. */
  handle?: string;
  state?: GraphState;
  /** The edge from its parent node, by its type. */
  edge?: string;
  /** Step 2: a step an agent labeled itself. */
  note?: boolean;
  children?: GraphNode[];
}

export interface GraphLink {
  from: string;
  to: string;
  label: string;
}

export interface TaskGraph {
  root: GraphNode;
  links: GraphLink[];
}

/** A task with several parts, mid-flight, three subagents off one step. */
const APPLE_PAY: TaskGraph = {
  root: {
    id: "epic",
    kind: "task",
    label: "Apple Pay for everyone",
    state: "working",
    children: [
      {
        id: "stripe",
        kind: "part",
        label: "Move card payments to Stripe",
        state: "done",
        edge: "part",
        children: [{ id: "pr499", kind: "pr", label: "#499", meta: "merged", state: "done", edge: "opened" }],
      },
      {
        id: "add",
        kind: "part",
        label: "Add Apple Pay to checkout",
        state: "working",
        edge: "part",
        children: [
          { id: "pr502", kind: "pr", label: "#502", meta: "approved", state: "working", edge: "opened" },
          { id: "n-sim", kind: "tried", label: "Pay in the simulator", edge: "tried", note: true, children: [
            { id: "n-sim-f", kind: "found", label: "Works with a test card", edge: "found", note: true },
          ] },
        ],
      },
      {
        id: "iphone",
        kind: "part",
        label: "Test on a real iPhone",
        state: "blocked",
        edge: "part",
        children: [
          { id: "n-card", kind: "blocked", label: "No real card on staging", edge: "blocked by", note: true },
        ],
      },
      {
        id: "review",
        kind: "part",
        label: "Review the double-charge fix",
        state: "working",
        edge: "part",
        children: [
          { id: "pr504", kind: "pr", label: "#504", meta: "in review", state: "working", edge: "opened" },
          {
            id: "sa-review",
            kind: "subagent",
            label: "review",
            handle: "builder:review",
            meta: "working",
            state: "working",
            edge: "subagent",
            children: [
              { id: "p-review", kind: "post", label: "One gap: a timeout after the charge", meta: "1m ago", edge: "posted" },
              { id: "n-timeout", kind: "found", label: "Timeout before the reply isn't refunded", edge: "found", note: true },
            ],
          },
          {
            id: "sa-tests",
            kind: "subagent",
            label: "tests",
            handle: "builder:tests",
            meta: "ended 2m ago",
            state: "done",
            edge: "subagent",
            children: [
              { id: "p-tests", kind: "post", label: "41 of 41 refund tests pass", meta: "3m ago", edge: "posted" },
              { id: "n-dbl", kind: "tried", label: "Double-click the Pay button", edge: "tried", note: true },
            ],
          },
          {
            id: "sa-retry",
            kind: "subagent",
            label: "retry",
            handle: "builder:retry",
            meta: "ended 6m ago",
            state: "done",
            edge: "subagent",
            children: [
              { id: "p-retry", kind: "post", label: "Retries reuse the idempotency key", meta: "7m ago", edge: "posted" },
              { id: "n-key", kind: "ruled-out", label: "A new key per retry", edge: "ruled out", note: true },
            ],
          },
        ],
      },
      {
        id: "launch",
        kind: "part",
        label: "Turn on Apple Pay for everyone",
        state: "waiting",
        edge: "part",
        children: [
          { id: "ask-friday", kind: "ask", label: "On for everyone Friday 9:00?", meta: "waiting on you", state: "waiting", edge: "asked" },
        ],
      },
    ],
  },
  links: [
    { from: "add", to: "stripe", label: "depends on" },
    { from: "iphone", to: "add", label: "depends on" },
    { from: "launch", to: "review", label: "depends on" },
  ],
};

/** A decision that's nearly done: a run settled it, parts carry it out. */
const DOUBLE_CHARGES: TaskGraph = {
  root: {
    id: "dc",
    kind: "task",
    label: "Double charges: refund or support?",
    state: "working",
    children: [
      {
        id: "dc-run",
        kind: "run",
        label: "concord",
        meta: "done",
        state: "done",
        edge: "ran",
        children: [
          { id: "dc-sum", kind: "summary", label: "context/summary/double-charges", edge: "saved" },
          {
            id: "dc-dec",
            kind: "decision",
            label: "Refund under $50",
            meta: "agreed",
            state: "done",
            edge: "decided",
            children: [
              {
                id: "dc-refund",
                kind: "part",
                label: "Refund under $50 automatically",
                state: "done",
                edge: "carried out",
                children: [{ id: "pr505", kind: "pr", label: "#505", meta: "merged", state: "done", edge: "opened" }],
              },
            ],
          },
        ],
      },
      {
        id: "dc-ask",
        kind: "ask",
        label: "Which go in before the sale?",
        state: "done",
        edge: "asked",
        children: [
          {
            id: "dc-ans",
            kind: "answer",
            label: "Chose 1 and 2",
            meta: "Morgan",
            state: "done",
            edge: "answered",
            children: [
              {
                id: "dc-alert",
                kind: "part",
                label: "Alert on a double charge",
                state: "done",
                edge: "chosen",
                children: [{ id: "pr507", kind: "pr", label: "#507", meta: "merged", state: "done", edge: "opened" }],
              },
              { id: "dc-receipt", kind: "part", label: "Move the receipt email", state: "dropped", edge: "not chosen" },
            ],
          },
        ],
      },
    ],
  },
  links: [],
};

/** The graph for a task, by the task's key. */
export function mockTaskGraph(key: string): TaskGraph | null {
  if (key === "work/apple-pay-for-everyone") return APPLE_PAY;
  if (key === "decisions/double-charge-refunds") return DOUBLE_CHARGES;
  return null;
}
