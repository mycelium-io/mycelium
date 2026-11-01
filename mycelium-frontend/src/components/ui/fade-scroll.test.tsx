// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FadeScroll, fadeMask } from "@/components/ui/fade-scroll";

/** jsdom lays nothing out, so the list's sizes are set by hand. */
function sized(el: HTMLElement, { scrollTop, clientHeight, scrollHeight }: Record<string, number>) {
  Object.defineProperty(el, "clientHeight", { configurable: true, value: clientHeight });
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollHeight });
  el.scrollTop = scrollTop;
}

describe("fadeMask", () => {
  it("fades only the edges with more past them", () => {
    expect(fadeMask(false, false)).toBeUndefined();
    expect(fadeMask(false, true)).toMatch(/^linear-gradient\(to bottom, black, .*transparent\)$/);
    expect(fadeMask(true, false)).toMatch(/^linear-gradient\(to bottom, transparent, .*, black\)$/);
  });
});

describe("<FadeScroll />", () => {
  it("fades the bottom while there is more below, and the top once scrolled past it", () => {
    render(<FadeScroll data-testid="list">rows</FadeScroll>);
    const list = screen.getByTestId("list");

    sized(list, { scrollTop: 0, clientHeight: 100, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(list).toHaveAttribute("data-fade-bottom");
    expect(list).not.toHaveAttribute("data-fade-top");

    sized(list, { scrollTop: 200, clientHeight: 100, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(list).toHaveAttribute("data-fade-top");
    expect(list).not.toHaveAttribute("data-fade-bottom");
  });

  it("draws no fade on a list that fits", () => {
    render(<FadeScroll data-testid="list">rows</FadeScroll>);
    const list = screen.getByTestId("list");
    sized(list, { scrollTop: 0, clientHeight: 300, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(list).not.toHaveAttribute("data-fade-top");
    expect(list).not.toHaveAttribute("data-fade-bottom");
    expect(list.style.maskImage).toBe("");
  });
});
