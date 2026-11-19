// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { GrowTextarea, supportsFieldSizing } from "./grow-textarea";

// jsdom has no `CSS` global, so these tests stub one to choose a path.
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function withFieldSizing(supported: boolean) {
  const supports = vi.fn((property: string, value: string) => supported && property === "field-sizing" && value === "content");
  vi.stubGlobal("CSS", { supports });
  return supports;
}

/** Gives every textarea a laid-out size, since jsdom lays nothing out. */
function laidOut({ height, scrollHeight, maxHeight }: { height: number; scrollHeight: number; maxHeight: string }) {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(height);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(height);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(scrollHeight);
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((el) => {
    const style = real(el);
    return new Proxy(style, {
      get: (target, key) => {
        if (key === "maxHeight") return maxHeight;
        if (key === "paddingTop" || key === "paddingBottom") return "4px";
        const v = Reflect.get(target, key);
        return typeof v === "function" ? v.bind(target) : v;
      },
    });
  });
}

describe("supportsFieldSizing", () => {
  it("is false when the browser has no CSS.supports", () => {
    vi.stubGlobal("CSS", undefined);
    expect(supportsFieldSizing()).toBe(false);
  });

  it("asks the browser about field-sizing: content", () => {
    const supports = withFieldSizing(true);
    expect(supportsFieldSizing()).toBe(true);
    expect(supports).toHaveBeenCalledWith("field-sizing", "content");
    withFieldSizing(false);
    expect(supportsFieldSizing()).toBe(false);
  });
});

describe("GrowTextarea without field-sizing", () => {
  it("leaves field-sizing and the CSS row limits off", () => {
    withFieldSizing(false);
    render(<GrowTextarea aria-label="Note" value="" onChange={() => {}} minRows={2} maxRows={6} className="w-full" />);
    const box = screen.getByLabelText("Note");
    expect(box.className).not.toContain("field-sizing");
    expect(box.className).toContain("w-full");
    expect(box.style.minHeight).toBe("");
    expect(box.style.maxHeight).toBe("");
    expect(box.style.overflowY).toBe("hidden");
  });

  it("passes its ref through", () => {
    withFieldSizing(false);
    const ref = { current: null as HTMLTextAreaElement | null };
    render(<GrowTextarea ref={ref} aria-label="Note" defaultValue="" minRows={1} maxRows={3} />);
    expect(ref.current).toBe(screen.getByLabelText("Note"));
  });
});

describe("GrowTextarea with field-sizing", () => {
  it("lets CSS grow it between its min and max rows", () => {
    withFieldSizing(true);
    render(<GrowTextarea aria-label="Note" value="" onChange={() => {}} minRows={2} maxRows={6} className="w-full" />);
    const box = screen.getByLabelText("Note");
    expect(box.className).toContain("[field-sizing:content]");
    expect(box.className).toContain("w-full");
    expect(box.style.height).toBe("");
    expect(box.style.minHeight).toContain("2lh");
    expect(box.style.maxHeight).toContain("6lh");
    expect(box.style.overflowY).toBe("hidden");
  });

  it("scrolls only once its text runs past the cap", () => {
    withFieldSizing(true);
    laidOut({ height: 160, scrollHeight: 400, maxHeight: "160px" });
    const onScrollsChange = vi.fn();
    render(<GrowTextarea aria-label="Note" value={"line\n".repeat(20)} onChange={() => {}} minRows={1} maxRows={6} onScrollsChange={onScrollsChange} />);
    expect(screen.getByLabelText("Note").style.overflowY).toBe("auto");
    expect(onScrollsChange).toHaveBeenLastCalledWith(true);
  });

  it("draws no scrollbar for a fraction of a pixel under the cap", () => {
    withFieldSizing(true);
    laidOut({ height: 80, scrollHeight: 81, maxHeight: "160px" });
    const onScrollsChange = vi.fn();
    render(<GrowTextarea aria-label="Note" value="short" onChange={() => {}} minRows={1} maxRows={6} onScrollsChange={onScrollsChange} />);
    expect(screen.getByLabelText("Note").style.overflowY).toBe("hidden");
    expect(onScrollsChange).not.toHaveBeenCalled();
  });
});
