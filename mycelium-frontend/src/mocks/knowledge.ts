// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: the checkout room's knowledge, as a graph of its memories.
 *
 * Each memory here is an ordinary memory with three proposed fields: a `kind`
 * (a fact, a finding, a dead end, or a decision the conductor saved), the task
 * it was learned in, and `derived-from`, a new relation beside `part-of`,
 * `depends-on`, `relates-to` and `supersedes` that says which memories it came
 * from. A memory is open while someone is still working on it and settled once
 * it holds. Tags are the room's own, for flavor.
 *
 * The room's graph is all of it. A task's graph is the same graph through one
 * lens: the memories that task produced, plus the ones from other tasks they
 * came from.
 */

export type KnowledgeKind = "fact" | "finding" | "dead-end" | "decision";

export interface KnowledgeTask {
  key: string;
  title: string;
}

export interface Knowledge {
  key: string;
  kind: KnowledgeKind;
  title: string;
  /** Who wrote it: a person, an agent, or a subagent (`builder:retry`). */
  by: string;
  /** The task it was learned in. */
  task: string;
  open?: boolean;
  /** Keys of the memories it came from. */
  derivedFrom?: string[];
  /** Keys of memories it bears on without coming from them. */
  relatesTo?: string[];
  tags?: string[];
  at: string;
}

export const CHECKOUT_TASKS: KnowledgeTask[] = [
  { key: "work/apple-pay-for-everyone", title: "Apple Pay for everyone" },
  { key: "decisions/double-charge-refunds", title: "Double charges" },
  { key: "work/payment-alerts", title: "Payment alerts" },
];

const APPLE = "work/apple-pay-for-everyone";
const DOUBLE = "decisions/double-charge-refunds";
const ALERTS = "work/payment-alerts";

export const CHECKOUT_KNOWLEDGE: Knowledge[] = [
  {
    key: "payments/stripe-dedupes-retries",
    kind: "fact",
    title: "Stripe dedupes a retry with the same key",
    by: "builder",
    task: APPLE,
    at: "3d ago",
  },
  {
    key: "payments/staging-test-cards",
    kind: "fact",
    title: "Staging only takes test cards",
    by: "morgan",
    task: APPLE,
    at: "2d ago",
  },
  {
    key: "payments/double-charges-last-month",
    kind: "fact",
    title: "38 double charges last month",
    by: "reviewer",
    task: DOUBLE,
    at: "2d ago",
  },
  {
    key: "payments/apple-pay-simulator",
    kind: "finding",
    title: "Apple Pay works in the simulator",
    by: "builder",
    task: APPLE,
    derivedFrom: ["payments/staging-test-cards"],
    at: "40m ago",
  },
  {
    key: "payments/real-iphone-needs-card",
    kind: "finding",
    title: "A real iPhone needs a live card",
    by: "morgan",
    task: APPLE,
    open: true,
    derivedFrom: ["payments/staging-test-cards"],
    tags: ["hardware"],
    at: "39m ago",
  },
  {
    key: "payments/new-key-per-retry",
    kind: "dead-end",
    title: "A new key for every retry",
    by: "builder:retry",
    task: APPLE,
    derivedFrom: ["payments/stripe-dedupes-retries"],
    at: "7m ago",
  },
  {
    key: "payments/retries-reuse-key",
    kind: "finding",
    title: "Retries reuse the key",
    by: "builder:retry",
    task: APPLE,
    derivedFrom: ["payments/stripe-dedupes-retries"],
    at: "6m ago",
  },
  {
    key: "payments/timeout-not-refunded",
    kind: "finding",
    title: "A timeout before the reply isn't refunded",
    by: "builder:review",
    task: APPLE,
    open: true,
    derivedFrom: ["payments/retries-reuse-key"],
    at: "1m ago",
  },
  {
    key: "payments/refund-test-12",
    kind: "fact",
    title: "Refund test 12 fails one run in ten",
    by: "builder:tests",
    task: APPLE,
    open: true,
    derivedFrom: ["payments/retries-reuse-key"],
    relatesTo: ["payments/timeout-not-refunded"],
    tags: ["flaky"],
    at: "3m ago",
  },
  {
    key: "payments/support-for-all",
    kind: "dead-end",
    title: "Send every double charge to support",
    by: "conductor",
    task: DOUBLE,
    derivedFrom: ["payments/double-charges-last-month"],
    at: "1d ago",
  },
  {
    key: "context/decision/double-charge-refunds",
    kind: "decision",
    title: "Refund under $50 on its own",
    by: "conductor",
    task: DOUBLE,
    derivedFrom: ["payments/double-charges-last-month", "payments/retries-reuse-key"],
    at: "1d ago",
  },
  {
    key: "payments/two-captures-in-2s",
    kind: "finding",
    title: "A double charge is two captures in 2s",
    by: "builder",
    task: ALERTS,
    derivedFrom: ["payments/double-charges-last-month"],
    at: "5h ago",
  },
  {
    key: "payments/alert-threshold",
    kind: "finding",
    title: "Alert on two captures in 10s",
    by: "builder",
    task: ALERTS,
    open: true,
    derivedFrom: ["payments/two-captures-in-2s"],
    tags: ["alerting"],
    at: "2h ago",
  },
];

/** The checkout room's knowledge, or null for any other room. */
export function mockRoomKnowledge(room: string): { tasks: KnowledgeTask[]; memories: Knowledge[] } | null {
  return room === "checkout" ? { tasks: CHECKOUT_TASKS, memories: CHECKOUT_KNOWLEDGE } : null;
}

/** Whether a task has a lens in the mock. */
export function mockHasLens(taskKey: string): boolean {
  return CHECKOUT_TASKS.some((t) => t.key === taskKey);
}
