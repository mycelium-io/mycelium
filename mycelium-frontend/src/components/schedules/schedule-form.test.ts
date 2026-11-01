// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { checkKey, dailyCron, defaultName, timingEdit, timingOf, timingWords } from "./schedule-form";

describe("schedule timing", () => {
  it("sends a preset as an interval and a daily time as a cron line", () => {
    expect(timingEdit({ kind: "every", every: "30m" })).toEqual({ every: "30m" });
    expect(timingEdit({ kind: "daily", time: "09:00", weekdays: true })).toEqual({ cron: "0 9 * * 1-5" });
    expect(dailyCron("17:30", false)).toBe("30 17 * * *");
  });

  it("tells a custom interval from a custom cron line by its spaces", () => {
    expect(timingEdit({ kind: "custom", text: " 45m " })).toEqual({ every: "45m" });
    expect(timingEdit({ kind: "custom", text: "*/10 * * * *" })).toEqual({ cron: "*/10 * * * *" });
  });

  it("opens a saved schedule where it is", () => {
    expect(timingOf(null)).toEqual({ kind: "every", every: "30m" });
    expect(timingOf({ every: "1h", cron: null })).toEqual({ kind: "every", every: "1h" });
    expect(timingOf({ every: "45m", cron: null })).toEqual({ kind: "custom", text: "45m" });
    expect(timingOf({ every: null, cron: "0 9 * * 1-5" })).toEqual({
      kind: "daily",
      time: "09:00",
      weekdays: true,
    });
    expect(timingOf({ every: null, cron: "*/10 * * * *" })).toEqual({ kind: "custom", text: "*/10 * * * *" });
  });

  it("round-trips a daily time through its cron line", () => {
    const t = { kind: "daily", time: "07:05", weekdays: false } as const;
    expect(timingOf({ every: null, cron: timingEdit(t).cron })).toEqual(t);
  });

  it("says a timing in words", () => {
    expect(timingWords({ kind: "every", every: "4h" })).toBe("every 4h");
    expect(timingWords({ kind: "daily", time: "09:00", weekdays: true })).toBe("every weekday at 09:00 UTC");
  });
});

describe("schedule checks and names", () => {
  it("treats every search as the one search option", () => {
    expect(checkKey("search:refund from:operator")).toBe("search");
    expect(checkKey("stale")).toBe("stale");
  });

  it("names a schedule from its agent and check when none is given", () => {
    expect(defaultName("builder", "assigned")).toBe("builder-assigned");
    expect(defaultName("Code Bot", "search:refund")).toBe("code-bot-search");
    expect(defaultName("", "")).toBe("schedule");
  });
});
