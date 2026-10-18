// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The room's activity log, moved from the board's Daily view to the Metrics
// page: the day grid, the streak and each member's lane.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityLog } from "./activity-log";
import type { ActivityEvent } from "@/lib/board/activity";

const NOW = Date.parse("2026-10-17T15:00:00Z");
const at = (hoursAgo: number) => new Date(NOW - hoursAgo * 3_600_000).toISOString();
const event = (id: string, actor: string, hoursAgo: number, title: string): ActivityEvent => ({
  id,
  at: at(hoursAgo),
  actor,
  actorKind: actor === "julia" ? "human" : "agent",
  action: "resolved",
  title,
  source: "board",
});

describe("<ActivityLog />", () => {
  it("counts today, draws the ten-week grid and one lane per member", () => {
    render(
      <ActivityLog
        events={[
          event("a", "builder", 1, "Add Apple Pay to checkout"),
          event("b", "julia", 2, "Pick the launch day"),
          event("c", "builder", 30, "Move card payments to Stripe"),
        ]}
        tz="UTC"
        onTz={vi.fn()}
        now={NOW}
      />,
    );
    expect(screen.getByText("2 logged today")).toBeInTheDocument();
    expect(screen.getByText(/2-day streak/)).toBeInTheDocument();
    // Seventy days, each a button you can pick.
    expect(screen.getAllByRole("button").filter(b => b.title.endsWith("logged"))).toHaveLength(70);
    expect(screen.getByText("@builder")).toBeInTheDocument();
    expect(screen.getByText("@julia")).toBeInTheDocument();
    expect(screen.getByText("Add Apple Pay to checkout")).toBeInTheDocument();
  });
});
