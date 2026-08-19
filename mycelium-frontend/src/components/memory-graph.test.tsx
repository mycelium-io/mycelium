// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryGraph } from "@/components/memory-graph";
import type { MemoryGraph as MemoryGraphData } from "@/lib/api";
import { savePlacements } from "@/lib/memory-graph-placements";

/** Matches an element by its *whole* visible text. `getByText`'s default
 *  matcher only reads an element's direct text nodes, and every summary count
 *  sits in its own styled child span, so "1 orphan" is otherwise unfindable. */
function wholeText(expected: string | RegExp) {
  return (_content: string, el: Element | null) => {
    const text = el?.textContent?.replace(/\s+/g, " ").trim() ?? "";
    return typeof expected === "string" ? text === expected : expected.test(text);
  };
}

function graph(over: Partial<MemoryGraphData> = {}): MemoryGraphData {
  return {
    nodes: [
      { key: "decisions/a", expandable: false, outbound: 1, inbound: 1 },
      { key: "decisions/b", expandable: false, outbound: 0, inbound: 1 },
      { key: "context/orphan", expandable: false, outbound: 0, inbound: 0 },
    ],
    edges: [{ source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true }],
    ...over,
  };
}

describe("<MemoryGraph />", () => {
  it("navigates when a node is clicked", async () => {
    const onNavigate = vi.fn();
    render(<MemoryGraph graph={graph()} onNavigate={onNavigate} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open decisions/a" }));

    expect(onNavigate).toHaveBeenCalledWith("decisions/a");
  });

  it("navigates on Enter for keyboard users", async () => {
    const onNavigate = vi.fn();
    render(<MemoryGraph graph={graph()} onNavigate={onNavigate} />);

    const node = screen.getByRole("button", { name: "Open decisions/b" });
    node.focus();
    await userEvent.keyboard("{Enter}");

    expect(onNavigate).toHaveBeenCalledWith("decisions/b");
  });

  it("marks a memory nothing links to as an orphan", () => {
    const { container } = render(<MemoryGraph graph={graph()} />);
    const orphanNode = screen.getByRole("button", { name: "Open context/orphan" });
    const circle = orphanNode.querySelector("circle");
    expect(circle).toHaveAttribute("stroke", "var(--yellow)");

    const linkedNode = screen.getByRole("button", { name: "Open decisions/a" });
    expect(linkedNode.querySelector("circle")).toHaveAttribute("stroke", "var(--paper)");

    // sanity: container actually rendered an svg with both nodes
    expect(container.querySelectorAll("circle")).toHaveLength(3);
  });

  it("draws no line for a link naming a memory that doesn't exist", () => {
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true },
            { source: "decisions/a", target: "missing", kind: "wikilink", resolved: false, error: "not_found" },
          ],
        })}
      />,
    );
    // Scoped to the graph canvas: lucide icons in the summary strip/legend
    // also render <line> elements internally.
    const canvas = screen.getByRole("group", { name: /memory link graph/i });
    expect(canvas.querySelectorAll("line")).toHaveLength(1);
  });

  it("draws a broken link between two real memories in the broken style", () => {
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            // Both ends exist; only the anchor is wrong. Dropping this would
            // hide a real authored connection and leave decisions/b looking
            // like it has one fewer inbound reference than it does.
            { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: false, error: "no_anchor" },
          ],
        })}
      />,
    );
    const canvas = screen.getByRole("group", { name: /memory link graph/i });
    const lines = canvas.querySelectorAll("line");
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveAttribute("stroke", "var(--red)");
    expect(lines[0].getAttribute("stroke-dasharray")).toBeTruthy();
    // Phrased with the vocabulary the detail view uses, not the raw API code.
    expect(lines[0].querySelector("title")?.textContent).toContain("no such section");

    // ...and it is not counted among the working links.
    expect(screen.getByText(wholeText("0 links"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 broken link"))).toBeInTheDocument();
  });

  it("summarizes memory, link, orphan and broken-link counts", () => {
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true },
            { source: "decisions/a", target: "missing", kind: "wikilink", resolved: false, error: "not_found" },
          ],
        })}
      />,
    );
    // Asserted as whole phrases, so each one pins the *count* rather than the
    // mere presence of the word — the legend also says "orphan", and matching
    // that would pass even with the counting removed.
    expect(screen.getByText(wholeText("3 memories"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 link"))).toBeInTheDocument(); // the broken one isn't drawn
    expect(screen.getByText(wholeText("1 orphan"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 broken link"))).toBeInTheDocument();
  });

  it("reports a cross-room reference apart from a genuine break", () => {
    // `myc://rooms/other/key` is documented syntax that just can't resolve
    // room-locally. Folding it into "broken" would fault a room for writing
    // something correct, so the strip names the two separately.
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            { source: "decisions/a", target: "typo", kind: "wikilink", resolved: false, error: "not_found" },
            { source: "decisions/b", target: "elsewhere", kind: "wikilink", resolved: false, error: "cross_room" },
          ],
        })}
      />,
    );

    expect(screen.getByText(wholeText("1 broken link"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 cross-room"))).toBeInTheDocument();
  });

  it("consumes the wheel event so the browser doesn't zoom the page too", () => {
    render(<MemoryGraph graph={graph()} />);
    const canvas = screen.getByRole("group", { name: /memory link graph/i });

    const before = canvas.querySelector("g")?.getAttribute("transform");
    const wheel = new WheelEvent("wheel", { deltaY: -100, cancelable: true, bubbles: true });
    // Dispatched natively rather than through fireEvent, which would route via
    // React's (passive) delegated listener and prove nothing about this fix.
    act(() => {
      canvas.dispatchEvent(wheel);
    });

    // React registers `wheel` passively, so this only holds while the listener
    // is attached natively with `{ passive: false }`.
    expect(wheel.defaultPrevented).toBe(true);
    expect(canvas.querySelector("g")?.getAttribute("transform")).not.toBe(before);
  });

  describe("drag to arrange", () => {
    // The component's viewBox, so a stubbed rect of this size makes one screen
    // pixel equal one graph unit and a drag's displacement exactly predictable.
    const VIEW_W = 1000;
    const VIEW_H = 700;

    /**
     * Renders with a canvas that reports a real size. jsdom's
     * `getBoundingClientRect` is all zeros, which makes the drag math divide by
     * zero and produce `translate(NaN,NaN)` — a "did it move?" assertion passes
     * on that, so without this the drag tests would be green on garbage.
     *
     * Wrapped in `StrictMode` because Next's App Router turns it on by default,
     * so its setup→cleanup→setup mount is the shape every dev page load takes.
     * Rendering bare hid a bug where that extra cleanup pass wiped the saved
     * arrangement; running every case this way keeps it from creeping back.
     */
    function renderGraph(props: Partial<Parameters<typeof MemoryGraph>[0]> = {}) {
      const utils = render(
        <StrictMode>
          <MemoryGraph graph={graph()} {...props} />
        </StrictMode>,
      );
      const canvas = screen.getByRole("group", { name: /memory link graph/i });
      canvas.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: VIEW_W, height: VIEW_H, right: VIEW_W, bottom: VIEW_H, x: 0, y: 0 }) as DOMRect;
      return { ...utils, canvas };
    }

    /** One press-move-release on a node, in screen coordinates. */
    function dragNode(node: Element, dx: number, dy: number, canvas: Element) {
      const opts = { bubbles: true, pointerId: 1, clientX: 100, clientY: 100 };
      act(() => {
        node.dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 100 + dx, clientY: 100 + dy }));
        canvas.dispatchEvent(new PointerEvent("pointerup", { ...opts, clientX: 100 + dx, clientY: 100 + dy }));
      });
    }

    function transformOf(node: Element) {
      return node.getAttribute("transform");
    }

    /** The numeric x/y out of a `translate(x,y)` transform. */
    function positionOf(node: Element) {
      const [x, y] = /translate\(([-\d.]+),([-\d.]+)\)/.exec(transformOf(node) ?? "")!.slice(1).map(Number);
      return { x, y };
    }

    function node(name: string) {
      return screen.getByRole("button", { name: `Open ${name}` });
    }

    it("moves a node by exactly the drag distance, leaving the others alone", () => {
      const { canvas } = renderGraph();
      const before = positionOf(node("decisions/a"));
      const otherBefore = transformOf(node("decisions/b"));

      dragNode(node("decisions/a"), 120, 60, canvas);

      const after = positionOf(node("decisions/a"));
      expect(after.x).toBeCloseTo(before.x + 120);
      expect(after.y).toBeCloseTo(before.y + 60);
      expect(transformOf(node("decisions/b"))).toBe(otherBefore);
    });

    it("keeps a connected edge attached to the node it follows", () => {
      const { canvas } = renderGraph();
      const line = canvas.querySelector("line")!;
      const before = { x1: Number(line.getAttribute("x1")), y1: Number(line.getAttribute("y1")) };

      // decisions/a is the edge's source, so x1/y1 must track it. This is the
      // assertion that fails if the edge ever goes back to the layout's baked
      // coordinates instead of reading live node positions.
      dragNode(node("decisions/a"), 150, 90, canvas);

      const after = canvas.querySelector("line")!;
      expect(Number(after.getAttribute("x1"))).toBeCloseTo(before.x1 + 150);
      expect(Number(after.getAttribute("y1"))).toBeCloseTo(before.y1 + 90);
    });

    it("does not open the drawer when the press was a drag", () => {
      const onNavigate = vi.fn();
      const { canvas } = renderGraph({ onNavigate });

      dragNode(node("decisions/a"), 120, 60, canvas);

      expect(onNavigate).not.toHaveBeenCalled();
    });

    it("opens the drawer from the press sequence alone, with no click event", () => {
      const onNavigate = vi.fn();
      const { canvas } = renderGraph({ onNavigate });
      const before = transformOf(node("decisions/a"));

      // 2px of tremor is under DRAG_THRESHOLD, so this is a click, not a drag.
      // Deliberately no synthetic `click`: pointer capture retargets the real
      // browser click to the <svg>, so a node-level onClick never fires and
      // asserting via a hand-dispatched click would test nothing real.
      dragNode(node("decisions/a"), 2, 1, canvas);

      expect(onNavigate).toHaveBeenCalledWith("decisions/a");
      // ...and tremor under the threshold must leave the node exactly put.
      expect(transformOf(node("decisions/a"))).toBe(before);
    });

    describe("persistence", () => {
      /** jsdom's own localStorage has no methods under some Node versions, so
       *  the component is given a working one explicitly. */
      function stubStorage() {
        const data = new Map<string, string>();
        vi.stubGlobal("localStorage", {
          getItem: (k: string) => data.get(k) ?? null,
          setItem: (k: string, v: string) => void data.set(k, v),
          removeItem: (k: string) => void data.delete(k),
        });
        return data;
      }

      /** The persisted positions map, whatever room key it landed under. */
      function stored(data: Map<string, string>): Record<string, unknown> {
        const raw = [...data.values()][0];
        return raw ? JSON.parse(raw).positions : {};
      }

      afterEach(() => vi.unstubAllGlobals());

      it("writes once for a whole drag, not once per pointermove", () => {
        vi.useFakeTimers();
        try {
          const data = stubStorage();
          const writes = vi.spyOn(
            localStorage as unknown as { setItem: (k: string, v: string) => void },
            "setItem",
          );
          const { canvas } = renderGraph({ roomName: "atlas" });
          const target = node("decisions/a");
          writes.mockClear();

          // Twenty intermediate positions, as a real gesture produces.
          act(() => {
            target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 100, clientY: 100 }));
            for (let i = 1; i <= 20; i++) {
              canvas.dispatchEvent(
                new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 100 + i * 5, clientY: 100 + i * 2 }),
              );
            }
            canvas.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 200, clientY: 140 }));
          });

          expect(writes).not.toHaveBeenCalled(); // still pending
          act(() => void vi.runAllTimers());
          expect(writes).toHaveBeenCalledTimes(1);
          expect(stored(data)).toHaveProperty("decisions/a");
        } finally {
          vi.useRealTimers();
        }
      });

      it("does not write on mount, so a StrictMode cleanup can't wipe the store", () => {
        // The regression this pins: mirroring `placed` outward meant the
        // mount-time cleanup pass saved the pre-hydration empty map over the
        // real one. Only a drag or a reset may ever write.
        const data = stubStorage();
        savePlacements("atlas", { "decisions/a": { x: 111, y: 222 } });

        renderGraph({ roomName: "atlas" });

        expect(stored(data)).toEqual({ "decisions/a": { x: 111, y: 222 } });
        expect(transformOf(node("decisions/a"))).toBe("translate(111,222)");
      });

      it("restores a room's arrangement after a remount", () => {
        stubStorage();
        const first = renderGraph({ roomName: "atlas" });
        dragNode(node("decisions/a"), 140, 70, first.canvas);
        const arranged = transformOf(node("decisions/a"));
        first.unmount();

        renderGraph({ roomName: "atlas" });

        expect(transformOf(node("decisions/a"))).toBe(arranged);
      });

      it("keeps one room's arrangement out of another's", () => {
        stubStorage();
        const first = renderGraph({ roomName: "atlas" });
        const original = transformOf(node("decisions/a"));
        dragNode(node("decisions/a"), 140, 70, first.canvas);
        const arranged = transformOf(node("decisions/a"));
        first.unmount();

        const other = renderGraph({ roomName: "different-room" });
        expect(transformOf(node("decisions/a"))).toBe(original);
        other.unmount();

        // ...and the original room still has its own.
        renderGraph({ roomName: "atlas" });
        expect(transformOf(node("decisions/a"))).toBe(arranged);
      });

      it("forgets the arrangement after a reset", async () => {
        const data = stubStorage();
        const first = renderGraph({ roomName: "atlas" });
        const original = transformOf(node("decisions/a"));
        dragNode(node("decisions/a"), 140, 70, first.canvas);
        await userEvent.click(screen.getByRole("button", { name: /reset layout/i }));
        first.unmount();

        expect(data.size).toBe(0); // the entry is removed, not left as an empty husk
        renderGraph({ roomName: "atlas" });
        expect(transformOf(node("decisions/a"))).toBe(original);
      });

      it("does not persist at all without a room", () => {
        const data = stubStorage();
        const first = renderGraph();
        const original = transformOf(node("decisions/a"));
        dragNode(node("decisions/a"), 140, 70, first.canvas);
        first.unmount();

        expect(data.size).toBe(0);
        renderGraph();
        expect(transformOf(node("decisions/a"))).toBe(original);
      });

      it("forgets a saved position once its memory disappears from the graph", () => {
        const data = stubStorage();
        const first = renderGraph({ roomName: "atlas" });
        dragNode(node("decisions/a"), 140, 70, first.canvas);
        first.unmount();
        expect(stored(data)).toHaveProperty("decisions/a");

        // decisions/a is gone from the payload — renamed or deleted. Its saved
        // position is unreachable now, so the component must prune it on load
        // and write the pruned map back, rather than carrying it forever.
        const shrunk = {
          nodes: [{ key: "decisions/b", expandable: false, outbound: 0, inbound: 1 }],
          edges: [],
        };
        // Pruning writes back on its own, at the moment it notices — the
        // component itself never persists anything the user didn't do.
        render(<MemoryGraph graph={shrunk} roomName="atlas" />);

        expect(screen.queryByRole("button", { name: "Open decisions/a" })).not.toBeInTheDocument();
        expect(stored(data)).not.toHaveProperty("decisions/a");
      });
    });

    it("offers a reset only once something has been moved, and restores the layout", async () => {
      const { canvas } = renderGraph();
      const original = transformOf(node("decisions/a"));

      expect(screen.queryByRole("button", { name: /reset layout/i })).not.toBeInTheDocument();

      dragNode(node("decisions/a"), 120, 60, canvas);
      await userEvent.click(screen.getByRole("button", { name: /reset layout/i }));

      expect(transformOf(node("decisions/a"))).toBe(original);
      expect(screen.queryByRole("button", { name: /reset layout/i })).not.toBeInTheDocument();
    });
  });

  it("reports no orphans or broken links when every memory is linked", () => {
    render(
      <MemoryGraph
        graph={{
          nodes: [
            { key: "decisions/a", expandable: false, outbound: 1, inbound: 1 },
            { key: "decisions/b", expandable: false, outbound: 1, inbound: 1 },
          ],
          edges: [
            { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true },
            { source: "decisions/b", target: "decisions/a", kind: "wikilink", resolved: true },
          ],
        }}
      />,
    );
    expect(screen.getByText(wholeText("2 memories"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("2 links"))).toBeInTheDocument();
    expect(screen.queryAllByText(wholeText(/^\d+ orphans?$/))).toHaveLength(0);
    expect(screen.queryAllByText(wholeText(/^\d+ broken links?$/))).toHaveLength(0);
  });
});
