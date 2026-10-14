// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFollowLatest, type FollowOptions } from "@/components/messages/use-follow-latest";

afterEach(() => vi.unstubAllGlobals());

/** A scroll region in a 400px window, `height` tall (changeable), scrolled to `top`. */
function region(top: number, height = 1000) {
  const el = document.createElement("div");
  const box = { height, top };
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => box.height });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: 400 });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => box.top,
    set: (v: number) => {
      box.top = Math.max(0, Math.min(v, box.height - 400));
    },
  });
  el.scrollTo = vi.fn(({ top: to }: ScrollToOptions) => {
    el.scrollTop = Number(to);
  }) as unknown as typeof el.scrollTo;
  return { el, box };
}

/** The reader scrolls to `top`. */
function scrollTo(el: HTMLElement, top: number) {
  el.scrollTop = top;
  act(() => {
    el.dispatchEvent(new Event("scroll"));
  });
}

const ids = (n: number, from = 1) => Array.from({ length: n }, (_, i) => `m${from + i}`);

function follow(el: HTMLElement, initial: FollowOptions) {
  return renderHook((opts: FollowOptions) => useFollowLatest(el, opts), { initialProps: initial });
}

describe("useFollowLatest", () => {
  it("opens at the newest row", () => {
    const { el } = region(0);
    const { result } = follow(el, { rows: ids(3) });
    expect(el.scrollTop).toBe(600);
    expect(result.current.atBottom).toBe(true);
  });

  it("keeps the reader at the bottom when a tall reply lands", () => {
    // The bug this replaces: "near the bottom" was measured after the reply was
    // drawn, so a reply taller than the margin counted against the reader.
    const { el, box } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3) });
    expect(el.scrollTop).toBe(600);
    box.height = 1800;
    rerender({ rows: ids(4) });
    expect(el.scrollTop).toBe(1400);
    expect(result.current.atBottom).toBe(true);
  });

  it("stays at the bottom when a message grows without a new row", () => {
    const observers: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(cb: () => void) {
          observers.push(cb);
        }
        observe() {}
        disconnect() {}
      },
    );
    const { el, box } = region(0);
    follow(el, { rows: ids(3) });
    box.height = 1300;
    act(() => observers.forEach((cb) => cb()));
    expect(el.scrollTop).toBe(900);
  });

  it("holds still when the reader has scrolled up, and counts what arrived", () => {
    const { el, box } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3) });
    scrollTo(el, 100);
    expect(result.current.atBottom).toBe(false);
    expect(result.current.unread).toBe(0);
    box.height = 1600;
    rerender({ rows: ids(5) });
    expect(el.scrollTop).toBe(100);
    expect(result.current.unread).toBe(2);
  });

  it("doesn't count the first page as new", () => {
    const { el } = region(0);
    const { result, rerender } = follow(el, { rows: null, startAt: "start" });
    rerender({ rows: ids(12), startAt: "start" });
    expect(result.current.unread).toBe(0);
  });

  it("opens at the top when asked to, and doesn't pull the reader down", () => {
    const { el, box } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3), startAt: "start" });
    expect(el.scrollTop).toBe(0);
    expect(result.current.atBottom).toBe(false);
    box.height = 1500;
    rerender({ rows: ids(4), startAt: "start" });
    expect(el.scrollTop).toBe(0);
    expect(result.current.unread).toBe(1);
  });

  it("keeps the reader's place when older messages load above", () => {
    const { el, box } = region(0);
    const { rerender } = follow(el, { rows: ids(3, 10) });
    scrollTo(el, 200);
    // 400px of older rows land above: what was on screen stays on screen.
    box.height = 1400;
    rerender({ rows: [...ids(3, 1), ...ids(3, 10)] });
    expect(el.scrollTop).toBe(600);
  });

  it("asks for older messages near the top, and while the view isn't full", () => {
    const onNearTop = vi.fn();
    const { el } = region(0, 300);
    follow(el, { rows: ids(2), onNearTop });
    expect(onNearTop).toHaveBeenCalled();
    onNearTop.mockClear();
    const tall = region(0);
    follow(tall.el, { rows: ids(5), onNearTop });
    onNearTop.mockClear();
    scrollTo(tall.el, 100);
    expect(onNearTop).toHaveBeenCalled();
  });

  it("goes back to the newest row when the reader sends", () => {
    const { el, box } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3), sent: null });
    scrollTo(el, 100);
    box.height = 1200;
    rerender({ rows: ids(3), sent: "p1" });
    expect(el.scrollTop).toBe(800);
    expect(result.current.atBottom).toBe(true);
  });

  it("counts by which rows arrived, past a list that drops its oldest", () => {
    const { el } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3) });
    scrollTo(el, 100);
    // Four arrive while the list keeps three: the mark has dropped off.
    rerender({ rows: ids(3, 5) });
    expect(result.current.unread).toBe(3);
  });

  it("counts only the rows asked to", () => {
    const { el } = region(0);
    const { result, rerender } = follow(el, { rows: ["a", "m1"], counted: ["m1"] });
    scrollTo(el, 100);
    rerender({ rows: ["a", "m1", "b", "c", "m2"], counted: ["m1", "m2"] });
    expect(result.current.unread).toBe(1);
  });

  it("starts over when the rows belong to something else", () => {
    const { el } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3), resetKey: "work/a" });
    scrollTo(el, 100);
    rerender({ rows: ids(4), resetKey: "work/a" });
    expect(result.current.unread).toBe(1);
    rerender({ rows: ids(20, 50), resetKey: "work/b" });
    expect(result.current.unread).toBe(0);
    expect(el.scrollTop).toBe(600);
  });

  it("jumps to the latest and clears the count", () => {
    const { el } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3) });
    scrollTo(el, 100);
    rerender({ rows: ids(4) });
    act(() => result.current.jump());
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(result.current.atBottom).toBe(true);
    expect(result.current.unread).toBe(0);
  });

  it("doesn't read a jump's own smooth scroll as the reader leaving, so a reply landing meanwhile is followed", () => {
    const { el, box } = region(0);
    const { result, rerender } = follow(el, { rows: ids(3) });
    scrollTo(el, 100);
    // A smooth scroll: it starts, and doesn't arrive at once.
    el.scrollTo = vi.fn() as unknown as typeof el.scrollTo;
    act(() => result.current.jump());
    scrollTo(el, 300); // on its way down
    expect(result.current.atBottom).toBe(true);
    box.height = 1600;
    el.scrollTo = vi.fn(({ top: to }: ScrollToOptions) => {
      el.scrollTop = Number(to);
    }) as unknown as typeof el.scrollTo;
    rerender({ rows: ids(4) });
    expect(el.scrollTop).toBe(1200);
    expect(result.current.atBottom).toBe(true);
  });

  it("sees where the reader stopped when they scrolled during a jump", () => {
    vi.useFakeTimers();
    try {
      const { el } = region(0);
      const { result } = follow(el, { rows: ids(3) });
      scrollTo(el, 100);
      el.scrollTo = vi.fn() as unknown as typeof el.scrollTo;
      act(() => result.current.jump());
      scrollTo(el, 50); // the reader scrolls back up mid-jump, and stops
      expect(result.current.atBottom).toBe(true);
      act(() => vi.advanceTimersByTime(1000));
      expect(result.current.atBottom).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("doesn't pull the reader off something they were taken to", () => {
    const { el, box } = region(0);
    const { rerender } = follow(el, { rows: ids(3), holding: true });
    expect(el.scrollTop).toBe(0);
    box.height = 1400;
    rerender({ rows: ids(4), holding: true });
    expect(el.scrollTop).toBe(0);
  });
});
