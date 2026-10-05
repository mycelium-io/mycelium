// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Ago, relativeTime } from "@/lib/relative-time";

const NOW = Date.parse("2026-10-04T18:00:00Z");
const ago = (ms: number) => NOW - ms;
const MIN = 60_000;

describe("relative time", () => {
  it("says how long ago, as short as it reads", () => {
    expect(relativeTime(ago(20_000), NOW)).toBe("now");
    expect(relativeTime(ago(2 * MIN), NOW)).toBe("2m ago");
    expect(relativeTime(ago(3 * 60 * MIN), NOW)).toBe("3h ago");
    expect(relativeTime(ago(26 * 60 * MIN), NOW)).toBe("yesterday");
    expect(relativeTime(ago(4 * 24 * 60 * MIN), NOW)).toBe("4d ago");
    expect(relativeTime(ago(30 * 24 * 60 * MIN), NOW)).not.toMatch(/ago/);
  });

  it("shows the exact time on hover, and nothing for a row that reads the same as the one above", () => {
    const fiveAgo = Date.now() - 5 * MIN;
    const { container } = render(
      <>
        <Ago at={fiveAgo} />
        <Ago at={fiveAgo - 1000} unlessSameAs={fiveAgo} />
      </>,
    );
    const stamps = container.querySelectorAll("time");
    expect(stamps).toHaveLength(1);
    expect(stamps[0].getAttribute("title")).toBeTruthy();
    expect(screen.getByText(/m ago$/)).toBeTruthy();
  });
});
