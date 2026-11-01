// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Shimmer, SPORE_FRAMES, SPORE_STILL, SporeMark } from "@/components/responding-mark";

function setReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({ matches: reduce && query.includes("reduce"), media: query })),
  );
  window.matchMedia = globalThis.matchMedia;
}

describe("<SporeMark />", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("grows through its frames while an agent works", () => {
    setReducedMotion(false);
    render(<SporeMark />);
    const mark = screen.getByTestId("spore-mark");
    const seen = new Set<string>();
    for (let i = 0; i < SPORE_FRAMES.length; i++) {
      seen.add(mark.textContent ?? "");
      act(() => vi.advanceTimersByTime(110));
    }
    expect(seen.size).toBe(SPORE_FRAMES.length);
  });

  it("stays a still dot when motion is reduced", () => {
    setReducedMotion(true);
    render(<SporeMark />);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByTestId("spore-mark")).toHaveTextContent(SPORE_STILL);
  });

  it("stops its timer once the last spore is gone", () => {
    setReducedMotion(false);
    const { unmount } = render(
      <>
        <SporeMark />
        <SporeMark offset={4} />
      </>,
    );
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("<Shimmer />", () => {
  it("keeps the words readable as text", () => {
    render(<Shimmer>@builder is responding…</Shimmer>);
    expect(screen.getByText("@builder is responding…")).toHaveClass("responding-shimmer");
  });
});
