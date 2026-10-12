// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { JumpToLatest, useJumpToLatest } from "@/components/jump-to-latest";

beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  }
});

/** A scroll region 1000px tall in a 400px window, scrolled to `top`. */
function region(top: number) {
  const el = document.createElement("div");
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: 1000 });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: 400 });
  el.scrollTop = top;
  el.scrollTo = vi.fn(({ top: to }: ScrollToOptions) => {
    el.scrollTop = Number(to);
  }) as unknown as typeof el.scrollTo;
  return el;
}

function scrollTo(el: HTMLElement, top: number) {
  el.scrollTop = top;
  act(() => {
    el.dispatchEvent(new Event("scroll"));
  });
}

describe("useJumpToLatest", () => {
  it("is at the bottom when the reader is there", () => {
    const el = region(600);
    const { result } = renderHook(() => useJumpToLatest(el, 3));
    expect(result.current.atBottom).toBe(true);
    expect(result.current.unread).toBe(0);
  });

  it("counts messages that land while the reader is scrolled up", () => {
    const el = region(600);
    const { result, rerender } = renderHook(({ count }) => useJumpToLatest(el, count), { initialProps: { count: 3 } });
    scrollTo(el, 100);
    expect(result.current.atBottom).toBe(false);
    expect(result.current.unread).toBe(0);
    rerender({ count: 5 });
    expect(result.current.unread).toBe(2);
  });

  it("doesn't count the first page of messages as new", () => {
    const el = region(0);
    const { result, rerender } = renderHook(({ count }: { count: number | null }) => useJumpToLatest(el, count), {
      initialProps: { count: null },
    });
    expect(result.current.atBottom).toBe(false);
    rerender({ count: 12 });
    expect(result.current.unread).toBe(0);
    rerender({ count: 13 });
    expect(result.current.unread).toBe(1);
  });

  it("scrolls to the latest and clears the count when asked", () => {
    const el = region(100);
    const { result, rerender } = renderHook(({ count }) => useJumpToLatest(el, count), { initialProps: { count: 3 } });
    rerender({ count: 4 });
    act(() => result.current.jump());
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(result.current.atBottom).toBe(true);
    expect(result.current.unread).toBe(0);
  });
});

describe("<JumpToLatest />", () => {
  it("says how many messages are new, or just Jump to latest", () => {
    const onClick = vi.fn();
    const { rerender } = render(<JumpToLatest unread={0} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<JumpToLatest unread={3} onClick={onClick} />);
    expect(screen.getByRole("button", { name: "Jump to latest, 3 new" })).toHaveTextContent("3 new messages");
  });
});
