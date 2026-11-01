import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { EpisodeSummary } from "@/lib/api";

vi.mock("@/components/flow-graph", () => ({ FlowGraph: () => null }));

import { FlowPanel } from "./flow-panel";

function episode(over: Partial<EpisodeSummary>): EpisodeSummary {
  return {
    short_id: "9a16789f",
    episode: "urn:ep",
    topic: "urn:topic",
    outcome: "resolved",
    subkind: null,
    participants: [],
    metrics: null,
    assignments: null,
    tasks: [],
    message_count: 0,
    updated_at: "2026-10-23T20:00:00Z",
    updated_by: "conductor",
    ...over,
  };
}

describe("FlowPanel's steps", () => {
  beforeEach(() => window.localStorage.setItem("mycelium.flow-panel.shown", "1"));

  it("says a step got no stance only where the step takes one", () => {
    render(
      <FlowPanel
        floor={null}
        episode={episode({
          flow: {
            name: "mixed",
            steps: [
              { id: "terms", to: "all", collect: "keywords", next: "review" },
              { id: "review", to: "reviewer", require: "stance", next: { accept: "done", reject: "terms" } },
              { id: "done", end: "resolved" },
            ],
          },
          trace: [
            { step: "terms", turn: 1, asked: ["builder", "reviewer"], next: "review" },
            { step: "review", turn: 2, asked: ["reviewer"], next: "done" },
          ],
        })}
      />,
    );
    const row = (step: string) => screen.getByText(step, { selector: "span.text-text" }).parentElement!;
    expect(row("terms")).toHaveTextContent("1termsbuilder, reviewer→ review");
    expect(row("review")).toHaveTextContent("2reviewreviewerno stance→ done");
  });
});
