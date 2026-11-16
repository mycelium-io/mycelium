// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: a task's graph, as the hub would work it out on read from what it
 * already stores: the task's parts (`part-of`) and their `depends-on`, each
 * part's pull request, the asks in its thread and their answers, conductor
 * runs and what they saved (`context/decision`, `context/summary`), and an
 * agent's subagents, branching off the step they worked on.
 *
 * Everything descriptive is a tag. A note is a short message an agent tags
 * (`#tried`, `#found`, or any word the room uses), hung off the step it was
 * posted in. A tagged reply to another message is a relationship of the room's
 * own (`#explains`), drawn between the two. A task or part can carry tags too.
 * A `tags/<name>` memory may give a tag a color and a description; a tag
 * without one is drawn plain.
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
  | "note";

export type GraphState = "done" | "working" | "open" | "blocked" | "waiting" | "dropped";

/** A tag's color, from its `tags/<name>` memory. */
export type TagTone = "accent" | "green" | "red" | "yellow" | "plain";

export interface RoomTag {
  name: string;
  tone: TagTone;
  /** From the tag's memory, shown on hover. */
  about?: string;
}

export interface GraphNode {
  id: string;
  kind: GraphKind;
  label: string;
  /** A quiet second word on the node: a PR's state, when a subagent ended. */
  meta?: string;
  /** A subagent's handle, for its tooltip. */
  handle?: string;
  state?: GraphState;
  /** The edge from its parent node, by its type. A note's edge is its tag. */
  edge?: string;
  /** The tags the node carries. */
  tags?: string[];
  children?: GraphNode[];
}

export interface GraphLink {
  from: string;
  to: string;
  label: string;
  /** Set when the link is a tagged reply: a relationship of the room's own. */
  tag?: string;
}

export interface TaskGraph {
  root: GraphNode;
  links: GraphLink[];
  /** The room's tags that have a memory. */
  tags: RoomTag[];
}

const note = (id: string, tag: string, label: string, by?: string): GraphNode => ({
  id,
  kind: "note",
  label,
  edge: `#${tag}`,
  tags: [tag],
  handle: by,
});

const CHECKOUT_TAGS: RoomTag[] = [
  { name: "tried", tone: "plain", about: "Something an agent tried" },
  { name: "found", tone: "green", about: "Something that turned out true" },
  { name: "ruled-out", tone: "red", about: "An approach we won't take, and why" },
  { name: "blocked-by", tone: "red", about: "What a step is waiting on outside the room" },
  { name: "flaky", tone: "yellow", about: "A test or check that fails some runs" },
  { name: "explains", tone: "accent", about: "A reply that explains the message it answers" },
  { name: "hardware", tone: "plain" },
];

/** A task with several parts, mid-flight, three subagents off one step. */
const APPLE_PAY: TaskGraph = {
  tags: CHECKOUT_TAGS,
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
          { ...note("n-sim", "tried", "Pay in the simulator", "builder"), children: [
            note("n-sim-f", "found", "Works with a test card", "builder"),
          ] },
        ],
      },
      {
        id: "iphone",
        kind: "part",
        label: "Test on a real iPhone",
        state: "blocked",
        edge: "part",
        tags: ["hardware"],
        children: [note("n-card", "blocked-by", "No real card on staging", "morgan")],
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
              note("n-timeout", "found", "Timeout before the reply isn't refunded", "builder:review"),
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
              note("n-flaky", "flaky", "Refund test 12 fails one run in ten", "builder:tests"),
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
              note("n-key", "ruled-out", "A new key per retry", "builder:retry"),
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
    // review's finding, posted as a reply to the tests' flaky note.
    { from: "n-timeout", to: "n-flaky", label: "#explains", tag: "explains" },
  ],
};

/** A decision that's nearly done: a run settled it, parts carry it out. */
const DOUBLE_CHARGES: TaskGraph = {
  tags: CHECKOUT_TAGS,
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
          note("dc-support", "ruled-out", "Send every one to support", "conductor"),
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
