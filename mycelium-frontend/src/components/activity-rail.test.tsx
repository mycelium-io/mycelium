// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The "Recently updated" rail: live work first, finished work behind one line,
// and each row saying what last happened to it.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityRail, lastChange, type ActivityItem, type ActivityUpdate } from "@/components/activity-rail";

const AT = Date.parse("2026-10-04T18:00:00Z");

function update(label: string, detail: string, subkind: string | null = null): ActivityUpdate {
  return { id: `${label}-${detail}`, time: "18:00:00", at: AT, label, detail, subkind };
}

function item(key: string, standing: string | null, updates: ActivityUpdate[]): ActivityItem {
  return {
    subject: `work/${key}`,
    title: key,
    episode: null,
    memoryKey: `work/${key}`,
    actors: [],
    lastActor: null,
    time: "18:00:00",
    at: AT,
    standing,
    note: null,
    updates,
  };
}

describe("<ActivityRail />", () => {
  it("keeps finished work behind one line, so the rows on show are the live ones", () => {
    const items = [
      item("blocked one", "blocked", [update("Blocked", "@ana", "blocked")]),
      item("done one", "resolved", [update("Resolved", "@sam", "resolved")]),
      item("done two", "resolved", [update("Resolved", "@sam", "resolved")]),
      item("claimed one", "claimed", [update("Claimed", "@ana", "claimed")]),
    ];
    render(<ActivityRail items={items} />);
    expect(screen.getByText("blocked one")).toBeTruthy();
    expect(screen.getByText("claimed one")).toBeTruthy();
    expect(screen.queryByText("done one")).toBeNull();
    expect(screen.getByText("Show 2 more")).toBeTruthy();
    expect(screen.getByText("2 done")).toBeTruthy();
  });

  it("doesn't count a lease running out as news in the header", () => {
    const items = [
      item("drained", "expired", [update("Expired", "held by @ana", "expired")]),
      item("held", "claimed", [update("Claimed", "@ana", "claimed")]),
    ];
    render(<ActivityRail items={items} />);
    expect(screen.getByText(/^1 claimed$/)).toBeTruthy();
    expect(screen.queryByText(/^\d+ expired$/)).toBeNull();
  });

  it("says what last happened to a row, not only when", () => {
    expect(lastChange(update("Activity", "@ana"))).toBe("@ana posted in the thread");
    expect(lastChange(update("Knowledge", "v3 · @sam"))).toBe("@sam edited its notes");
    expect(lastChange(update("Claimed", "@ana", "claimed"))).toBe("claimed by @ana");
  });

  it("says an expired lease ran out on its holder, rather than that the holder expired it", () => {
    expect(lastChange(update("Expired", "held by @ana", "expired"))).toBe("@ana's lease ran out");
    render(<ActivityRail items={[item("drained", "expired", [update("Expired", "held by @ana", "expired")])]} />);
    expect(screen.getByText("@ana's lease ran out")).toBeTruthy();
  });

  it("says whose turn it is when the floor was the last thing to move", () => {
    expect(lastChange(update("Floor", "Ship it · @api, @sec", "floor"))).toBe("turn for @api, @sec");
    expect(lastChange(update("Floor", "Ship it · held by @conductor", "floor"))).toBe("@conductor's turn");
    expect(lastChange(update("Floor", "Ship it · released", "floor"))).toBe("floor open");
    // A task title that happens to say "released" is not the floor opening.
    expect(lastChange(update("Floor", "Fix released builds · @api", "floor"))).toBe("@api's turn");
  });
});
