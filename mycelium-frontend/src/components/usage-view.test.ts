import { describe, expect, it } from "vitest";
import { bucket, fmtHours, waysOf } from "./usage-view";
import { usageKpis } from "@/mocks/fixtures";

describe("usage view", () => {
  it("says hours the way a person would", () => {
    expect(fmtHours(null)).toBe("-");
    expect(fmtHours(0.3)).toBe("18m");
    expect(fmtHours(5.4)).toBe("5.4h");
    expect(fmtHours(30)).toBe("30h");
    expect(fmtHours(96)).toBe("4d");
  });

  it("shows a month by day and a quarter by week, newest last", () => {
    expect(bucket(usageKpis(30).daily)).toHaveLength(30);
    const weeks = bucket(usageKpis(90).daily);
    expect(weeks).toHaveLength(13);
    const quarter = usageKpis(90).daily;
    expect(weeks.reduce((n, w) => n + w.filed, 0)).toBe(quarter.reduce((n, d) => n + d.filed, 0));
    expect(weeks[weeks.length - 1].label).toBe(quarter[quarter.length - 7].day.slice(5));
  });

  it("lists every way of starting work with how often it ended well", () => {
    const ways = waysOf(usageKpis(30));
    expect(ways[0]).toMatchObject({ name: "Tasks resolved", well: null });
    const review = ways.find(w => w.name === "Review");
    expect(review?.well).toBeCloseTo(14 / 16);
    expect(review?.wellWord).toBe("passed");
    const settle = ways.find(w => w.name === "Settle");
    expect(settle).toMatchObject({ from: "negotiation", wellWord: "converged" });
  });
});
