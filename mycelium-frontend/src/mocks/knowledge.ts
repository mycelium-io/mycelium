// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The checkout mock room's knowledge, as the hub's `/knowledge` sends it
 * (`services/knowledge.py`): what its team learned, each piece with its kind,
 * the task it was learned in, who wrote it, and what it came from. Served by
 * the mock hub (`mocks/handlers.ts`), so the app reads it the way it reads a
 * real hub's.
 */

import type { KnowledgeKind, KnowledgeTask, KnowledgeWire } from "@/lib/knowledge";

/** A mock memory: the wire's fields, with how long ago it changed. */
interface Knowledge {
  key: string;
  kind: KnowledgeKind;
  title: string;
  by: string;
  task: string;
  open?: boolean;
  derivedFrom?: string[];
  relatesTo?: string[];
  tags?: string[];
  /** "3d ago", "5h ago", "1m ago". */
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

const UNIT_MS: Record<string, number> = { m: 60_000, h: 3_600_000, d: 86_400_000 };

function isoAgo(at: string, now: number): string {
  const found = /^(\d+)([mhd]) ago$/.exec(at);
  return new Date(now - (found ? Number(found[1]) * UNIT_MS[found[2]] : 0)).toISOString();
}

/** A room's knowledge as the hub sends it: the checkout room's, and nothing
 *  for any other. */
export function mockKnowledgeWire(
  room: string,
  now = Date.now(),
): { tasks: KnowledgeTask[]; memories: KnowledgeWire[] } {
  if (room !== "checkout") return { tasks: [], memories: [] };
  return {
    tasks: CHECKOUT_TASKS,
    memories: CHECKOUT_KNOWLEDGE.map((m) => ({
      key: m.key,
      kind: m.kind,
      title: m.title,
      by: m.by,
      task: m.task,
      open: !!m.open,
      derived_from: m.derivedFrom ?? [],
      relates_to: m.relatesTo ?? [],
      tags: m.tags ?? [],
      updated_at: isoAgo(m.at, now),
    })),
  };
}
