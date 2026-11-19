// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { describe, expect, it, vi } from "vitest";
import type { Knowledge, KnowledgeTask, KnowledgeWire } from "@/lib/knowledge";
import { fromWire } from "@/lib/knowledge";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const TASK = "work/apple-pay-for-everyone";
const OTHER = "work/payment-alerts";
const TASKS: KnowledgeTask[] = [
  { key: TASK, title: "Apple Pay for everyone" },
  { key: OTHER, title: "Payment alerts" },
];

function wire(over: Partial<KnowledgeWire> & Pick<KnowledgeWire, "key" | "title">): KnowledgeWire {
  return {
    kind: "finding",
    by: "builder",
    task: TASK,
    open: false,
    derived_from: [],
    relates_to: [],
    tags: [],
    updated_at: "2026-11-16T10:00:00Z",
    ...over,
  };
}

const WIRE: KnowledgeWire[] = [
  wire({ key: "payments/stripe", title: "Stripe dedupes a retry", kind: "fact", updated_at: "2026-11-14T10:00:00Z" }),
  wire({
    key: "payments/new-key",
    title: "A new key for every retry",
    kind: "dead-end",
    by: "builder:retry",
    derived_from: ["payments/stripe"],
  }),
  wire({
    key: "payments/reuse",
    title: "Retries reuse the key",
    by: "builder:retry",
    open: true,
    derived_from: ["payments/stripe"],
    tags: ["flaky"],
    updated_at: "2026-11-15T10:00:00Z",
  }),
  wire({
    key: "payments/alert",
    title: "Alert on two captures in 10s",
    task: OTHER,
    derived_from: ["payments/reuse"],
  }),
  wire({ key: "payments/webhooks", title: "Webhooks arrive in order", kind: "fact", task: OTHER }),
];
const MEMORIES: Knowledge[] = WIRE.map(fromWire);

const api = vi.hoisted(() => ({ fetchKnowledge: vi.fn() }));
vi.mock("@/lib/api", () => ({
  MEMORIES_MAX: 5000,
  fetchKnowledge: api.fetchKnowledge,
  fetchMemorySummaries: vi.fn().mockResolvedValue([]),
  fetchMemoryGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
  fetchMemory: vi.fn(),
  searchMemories: vi.fn(),
  deleteMemory: vi.fn(),
}));

import { KnowledgeGraph } from "@/components/knowledge-graph";
import { MemoryGraphView } from "@/components/memory-graph-view";
import { MemoryPanel } from "@/components/memory-panel";
import { TaskMemories } from "@/components/task/task-memories";

describe("the hub's knowledge, as the app reads it", () => {
  it("renames the wire's fields and keeps a memory with no task", () => {
    const m = fromWire(wire({ key: "k", title: "t", task: null, derived_from: ["a"], relates_to: ["b"] }));
    expect(m).toMatchObject({ task: "", derivedFrom: ["a"], relatesTo: ["b"], updatedAt: "2026-11-16T10:00:00Z" });
  });
});

describe("a task's Memories", () => {
  it("lists open ones first, then the newest, with who wrote each", () => {
    render(<TaskMemories memories={MEMORIES.filter((m) => m.task === TASK)} onGraph={() => {}} />);
    const section = screen.getByRole("region", { name: "Memories" });
    expect(within(section).getByText("1 open")).toBeInTheDocument();
    const titles = within(section)
      .getAllByRole("button")
      .map((b) => b.getAttribute("title"))
      .filter(Boolean);
    expect(titles).toEqual(["payments/reuse", "payments/new-key", "payments/stripe"]);
    expect(within(section).getAllByText("builder:retry")).toHaveLength(2);
  });
});

describe("the knowledge graph", () => {
  it("through a task's lens shows what it produced and where those went, not the rest", () => {
    render(<KnowledgeGraph tasks={TASKS} memories={MEMORIES} lens={TASK} />);
    expect(screen.getByText("Retries reuse the key")).toBeInTheDocument();
    // Fed by this task's finding, so it's in the picture, named by its task.
    expect(screen.getByText("Alert on two captures in 10s")).toBeInTheDocument();
    expect(screen.getByText("Payment alerts")).toBeInTheDocument();
    expect(screen.queryByText("Webhooks arrive in order")).not.toBeInTheDocument();
    expect(screen.getByText("3 memories")).toBeInTheDocument();
    expect(screen.getByText("1 open")).toBeInTheDocument();
  });

  it("filters by a tag", () => {
    render(<KnowledgeGraph tasks={TASKS} memories={MEMORIES} />);
    fireEvent.click(screen.getByRole("button", { name: "#flaky" }));
    const node = (title: string) => screen.getByText(title).closest("button")!;
    expect(node("Retries reuse the key").className).not.toContain("opacity-40");
    expect(node("Stripe dedupes a retry").className).toContain("opacity-40");
  });
});

describe("the room's memory graph", () => {
  it("draws what the team learned when there is any", async () => {
    api.fetchKnowledge.mockResolvedValue({ tasks: TASKS, memories: MEMORIES });
    renderWithSWR(<MemoryGraphView roomName="checkout" />);
    expect(await screen.findByText("Webhooks arrive in order")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All tasks" })).toBeInTheDocument();
  });
});

describe("the Memory panel", () => {
  it("says how many are open, and opens on what was learned with the folders a click away", async () => {
    api.fetchKnowledge.mockResolvedValue({ tasks: TASKS, memories: MEMORIES });
    renderWithSWR(
      <MemoryPanel roomName="checkout" onOpenMemory={() => {}} />,
    );
    expect(await screen.findByText("1 open")).toBeInTheDocument();
    expect(await screen.findByText("Retries reuse the key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Learned" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Folders" }));
    await waitFor(() => expect(screen.queryByText("Retries reuse the key")).not.toBeInTheDocument());
  });
});
