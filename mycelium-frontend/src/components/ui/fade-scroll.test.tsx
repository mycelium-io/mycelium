// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FadeScroll } from "@/components/ui/fade-scroll";

/** jsdom lays nothing out, so the list's sizes are set by hand. */
function sized(el: HTMLElement, { scrollTop, clientHeight, scrollHeight }: Record<string, number>) {
  Object.defineProperty(el, "clientHeight", { configurable: true, value: clientHeight });
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollHeight });
  el.scrollTop = scrollTop;
}

const blurs = (container: HTMLElement) =>
  [...container.querySelectorAll("[data-edge-blur]")].map((el) => el.getAttribute("data-edge-blur"));

describe("<FadeScroll />", () => {
  it("blurs the bottom while there is more below, and the top once scrolled past it", () => {
    const { container } = render(<FadeScroll data-testid="list">rows</FadeScroll>);
    const list = screen.getByTestId("list");

    sized(list, { scrollTop: 0, clientHeight: 100, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(blurs(container)).toEqual(["bottom"]);

    sized(list, { scrollTop: 100, clientHeight: 100, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(blurs(container)).toEqual(["top", "bottom"]);

    sized(list, { scrollTop: 200, clientHeight: 100, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(blurs(container)).toEqual(["top"]);
  });

  it("blurs nothing on a list that fits", () => {
    const { container } = render(<FadeScroll data-testid="list">rows</FadeScroll>);
    const list = screen.getByTestId("list");
    sized(list, { scrollTop: 0, clientHeight: 300, scrollHeight: 300 });
    fireEvent.scroll(list);
    expect(blurs(container)).toEqual([]);
  });
});
