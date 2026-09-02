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

/** What a browser actually sends while a left-button drag is underway.
 *
 *  `PointerEventInit` defaults `buttons` to 0 and `isPrimary` to false — a
 *  pointer with nothing held down that isn't the primary one — and the canvas is
 *  built to decline exactly that (it's how a released-off-canvas drag and a
 *  second finger are rejected). Synthetic gestures have to spell both out or
 *  they test a press no browser sends. */
const PRESS = { bubbles: true, pointerId: 1, button: 0, buttons: 1, isPrimary: true } as const;

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

  it("marks a fully-isolated memory (orphan) with a yellow dashed border", () => {
    const { container } = render(<MemoryGraph graph={graph()} />);
    // context/orphan: inbound=0, outbound=0 → orphan → yellow dashed
    const orphanNode = screen.getByRole("button", { name: "Open context/orphan" });
    const circle = orphanNode.querySelector("circle");
    expect(circle).toHaveAttribute("stroke", "var(--yellow)");
    expect(circle).toHaveAttribute("stroke-dasharray", "3 2");

    // decisions/a: inbound=1, outbound=1 → normal → paper border
    const linkedNode = screen.getByRole("button", { name: "Open decisions/a" });
    expect(linkedNode.querySelector("circle")).toHaveAttribute("stroke", "var(--paper)");

    // decisions/b: inbound=1, outbound=0 → leaf → muted-foreground dashed
    const leafNode = screen.getByRole("button", { name: "Open decisions/b" });
    expect(leafNode.querySelector("circle")).toHaveAttribute("stroke", "var(--muted-foreground)");
    expect(leafNode.querySelector("circle")).toHaveAttribute("stroke-dasharray", "2 3");

    // sanity: container actually rendered an svg with all three nodes
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
    // Dead references (no target node) don't appear in the broken-link count —
    // the strip only reflects what's drawn. `mycelium memory --check` is where
    // dead refs surface.
    expect(screen.queryByText(wholeText("1 broken link"))).not.toBeInTheDocument();
    expect(screen.getByText(wholeText("1 link"))).toBeInTheDocument();
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

  it("summarizes memory, link, orphan, leaf and broken-link counts", () => {
    // decisions/a: inbound=1, outbound=1 → normal
    // decisions/b: inbound=1, outbound=0 → leaf
    // context/orphan: inbound=0, outbound=0 → orphan
    //
    // The broken edge targets context/orphan (a real node in the graph), so it
    // is drawn as a red dashed arc and counted. A `not_found` edge whose target
    // isn't a node at all can't be drawn and therefore doesn't appear in the
    // strip — those dead references are surfaced by the integrity system instead.
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true },
            { source: "decisions/a", target: "context/orphan", kind: "wikilink", resolved: false, error: "no_anchor" },
          ],
        })}
      />,
    );
    // Asserted as whole phrases, so each one pins the *count* rather than the
    // mere presence of the word — the legend also says "orphan"/"leaf", and
    // matching partial text would pass even with the counting removed.
    expect(screen.getByText(wholeText("3 memories"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 link"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 orphan"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 leaf"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 broken link"))).toBeInTheDocument();
  });

  it("reports a cross-room reference apart from a genuine break", () => {
    // `myc://rooms/other/key` is documented syntax that just can't resolve
    // room-locally. Folding it into "broken" would fault a room for writing
    // something correct, so the strip names the two separately.
    //
    // The genuine break targets context/orphan (a real node) so it is drawn as a
    // red arc and counted. The cross-room reference targets a non-node, so it
    // never draws — it's counted separately using brokenAttributable (source-only
    // visibility check) since the target won't be in the room at all.
    render(
      <MemoryGraph
        graph={graph({
          edges: [
            { source: "decisions/a", target: "context/orphan", kind: "wikilink", resolved: false, error: "no_anchor" },
            { source: "decisions/b", target: "elsewhere", kind: "wikilink", resolved: false, error: "cross_room" },
          ],
        })}
      />,
    );

    expect(screen.getByText(wholeText("1 broken link"))).toBeInTheDocument();
    expect(screen.getByText(wholeText("1 cross-room"))).toBeInTheDocument();
  });

  it("gives context/ and decisions/ different colors", () => {
    // These two hashed to the same palette slot under the previous scheme, so
    // the two namespaces almost every room has rendered identically. Named
    // explicitly rather than testing distinctness in the abstract, because this
    // exact pair is the case that shipped broken.
    render(
      <MemoryGraph
        graph={{
          nodes: [
            { key: "context/goal", expandable: false, outbound: 0, inbound: 0 },
            { key: "decisions/db", expandable: false, outbound: 0, inbound: 0 },
          ],
          edges: [],
        }}
      />,
    );
    const fill = (key: string) =>
      screen.getByRole("button", { name: `Open ${key}` }).querySelector("circle")?.getAttribute("fill");

    expect(fill("context/goal")).not.toBe(fill("decisions/db"));
  });

  it("colors every namespace distinctly up to the size of the palette", () => {
    const namespaces = ["a", "b", "c", "d", "e", "f", "g", "h"];
    render(
      <MemoryGraph
        graph={{
          nodes: namespaces.map(ns => ({ key: `${ns}/x`, expandable: false, outbound: 0, inbound: 0 })),
          edges: [],
        }}
      />,
    );
    const fills = namespaces.map(
      ns => screen.getByRole("button", { name: `Open ${ns}/x` }).querySelector("circle")?.getAttribute("fill"),
    );

    expect(new Set(fills).size).toBe(namespaces.length);
  });

  it("wraps the palette past its 8th namespace rather than inventing a color", async () => {
    // Pinned as the documented ceiling, not as desirable: a 9th hue would have to
    // come from the arc reserved for broken links and orphans. The legend still
    // names every namespace, so the collision is readable rather than silent.
    const namespaces = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
    render(
      <MemoryGraph
        graph={{
          nodes: namespaces.map(ns => ({ key: `${ns}/x`, expandable: false, outbound: 0, inbound: 0 })),
          edges: [],
        }}
      />,
    );
    const fill = (ns: string) =>
      screen.getByRole("button", { name: `Open ${ns}/x` }).querySelector("circle")?.getAttribute("fill");

    expect(fill("i")).toBe(fill("a"));
    // Legend is collapsed by default; open it to check the button is present.
    await userEvent.click(screen.getByRole("button", { name: /expand legend/i }));
    expect(screen.getByRole("button", { name: /hide i/i })).toBeInTheDocument();
  });

  describe("filtering", () => {
    // Two namespaces and two link types, so each filter has something to remove
    // and something to leave behind.
    const mixed: MemoryGraphData = {
      nodes: [
        { key: "decisions/a", expandable: false, outbound: 2, inbound: 0 },
        { key: "decisions/b", expandable: false, outbound: 0, inbound: 1 },
        { key: "context/c", expandable: false, outbound: 0, inbound: 1 },
      ],
      edges: [
        { source: "decisions/a", target: "decisions/b", kind: "wikilink", resolved: true },
        { source: "decisions/a", target: "context/c", kind: "relation", relation: "depends-on", resolved: true },
      ],
    };

    function lines() {
      return screen.getByRole("group", { name: /memory link graph/i }).querySelectorAll("line");
    }

    async function openLegend() {
      await userEvent.click(screen.getByRole("button", { name: /expand legend/i }));
    }

    it("hides a namespace's memories, and the edges that reached them", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      expect(lines()).toHaveLength(2);

      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));

      expect(screen.queryByRole("button", { name: "Open context/c" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open decisions/a" })).toBeInTheDocument();
      // The depends-on edge pointed at the hidden memory, so it goes too —
      // rather than being left dangling at a node that isn't drawn.
      expect(lines()).toHaveLength(1);
    });

    it("hides one relation type without touching the memories", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();

      await userEvent.click(screen.getByRole("button", { name: /hide depends-on edges/i }));

      expect(lines()).toHaveLength(1);
      expect(screen.getByRole("button", { name: "Open context/c" })).toBeInTheDocument();
    });

    it("counts what's on screen, and says what it's a subset of", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      expect(screen.getByText(wholeText("3 memories"))).toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));

      expect(screen.getByText(wholeText("2 memories of 3"))).toBeInTheDocument();
      expect(screen.getByText(wholeText("1 link"))).toBeInTheDocument();
    });

    it("does not reclassify a leaf as an orphan when its referrers are hidden", async () => {
      // decisions/a: inbound=0, outbound=2 → root (entry point)
      // decisions/b: inbound=1, outbound=0 → leaf
      // context/c:   inbound=1, outbound=0 → leaf
      // Hiding decisions/ removes decisions/a and decisions/b from view.
      // context/c still has inbound=1 in its node data — that's a room fact —
      // so it must stay a leaf, not become an orphan.
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      expect(screen.getByText(wholeText("1 root"))).toBeInTheDocument();
      expect(screen.getByText(wholeText("2 leaves"))).toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: /hide decisions/i }));

      // context/c is still visible and still a leaf — not reclassified.
      expect(screen.getByRole("button", { name: "Open context/c" })).toBeInTheDocument();
      expect(screen.queryByText(wholeText("1 orphan"))).not.toBeInTheDocument();
      expect(screen.getByText(wholeText("1 leaf"))).toBeInTheDocument();
    });

    it("does not highlight a neighbor reached only through a hidden edge", async () => {
      // Hover dims everything that isn't a neighbor. Once the depends-on edge is
      // filtered out, context/c is no longer connected to anything on screen, so
      // highlighting it would assert a link the canvas isn't drawing.
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      const opacityOf = (key: string) =>
        screen.getByRole("button", { name: `Open ${key}` }).getAttribute("opacity");

      await userEvent.click(screen.getByRole("button", { name: /hide depends-on edges/i }));
      await userEvent.hover(screen.getByRole("button", { name: "Open decisions/a" }));

      // Still a neighbor: the wikilink to decisions/b is drawn.
      expect(opacityOf("decisions/b")).toBe("1");
      // Not a neighbor any more: its only edge is hidden.
      expect(opacityOf("context/c")).not.toBe("1");
    });

    it("stops dimming the canvas once the hovered memory is filtered away", async () => {
      // Hiding a namespace unmounts its nodes without firing mouseleave, so the
      // hovered key can outlive the node. Left uncorrected, every remaining node
      // stays dimmed against a neighbour that isn't on screen to explain it.
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      const opacityOf = (key: string) =>
        screen.getByRole("button", { name: `Open ${key}` }).getAttribute("opacity");

      await userEvent.hover(screen.getByRole("button", { name: "Open context/c" }));
      expect(opacityOf("decisions/b")).not.toBe("1"); // dimmed, as a non-neighbour

      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));

      expect(opacityOf("decisions/a")).toBe("1");
      expect(opacityOf("decisions/b")).toBe("1");
    });

    it("starts a new payload unfiltered", async () => {
      // Filters are keyed by namespace name, so carrying them across a refresh
      // would hide part of a graph the reader never filtered.
      const { rerender } = render(<MemoryGraph graph={mixed} />);
      await openLegend();
      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));
      expect(screen.queryByRole("button", { name: "Open context/c" })).not.toBeInTheDocument();

      rerender(<MemoryGraph graph={{ ...mixed }} />);

      expect(screen.getByRole("button", { name: "Open context/c" })).toBeInTheDocument();
    });

    it("restores everything with one click, and only offers that while filtered", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));
      await userEvent.click(screen.getByRole("button", { name: /clear filters/i }));

      expect(screen.getByRole("button", { name: "Open context/c" })).toBeInTheDocument();
      expect(lines()).toHaveLength(2);
      expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();
    });

    it("says so rather than showing a blank canvas when everything is hidden", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();

      await userEvent.click(screen.getByRole("button", { name: /hide context/i }));
      await userEvent.click(screen.getByRole("button", { name: /hide decisions/i }));

      expect(screen.getByText(/nothing to show/i)).toBeInTheDocument();
    });

    it("reports each toggle's state to assistive tech", async () => {
      render(<MemoryGraph graph={mixed} />);
      await openLegend();
      const context = screen.getByRole("button", { name: /hide context/i });
      expect(context).toHaveAttribute("aria-pressed", "true");

      await userEvent.click(context);

      expect(screen.getByRole("button", { name: /show context/i })).toHaveAttribute("aria-pressed", "false");
    });
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
      const opts = { ...PRESS, clientX: 100, clientY: 100 };
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
            target.dispatchEvent(new PointerEvent("pointerdown", { ...PRESS, clientX: 100, clientY: 100 }));
            for (let i = 1; i <= 20; i++) {
              canvas.dispatchEvent(
                new PointerEvent("pointermove", { ...PRESS, clientX: 100 + i * 5, clientY: 100 + i * 2 }),
              );
            }
            canvas.dispatchEvent(new PointerEvent("pointerup", { ...PRESS, clientX: 200, clientY: 140 }));
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

    it("does not yank a half-dragged node when the zoom changes mid-gesture", () => {
      const { canvas } = renderGraph();
      const target = node("decisions/a");
      const opts = { ...PRESS, clientX: 100, clientY: 100 };

      act(() => {
        target.dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 200, clientY: 100 }));
      });
      const midDrag = positionOf(node("decisions/a"));

      // Separate acts on purpose: the move has to run against a handler that has
      // re-rendered with the new scale, which is what makes this a *mid-gesture*
      // zoom rather than two events sharing one stale closure.
      act(() => {
        canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, cancelable: true, bubbles: true }));
      });
      act(() => {
        // The pointer has not moved, so neither should the node. Measuring the
        // whole displacement from the press instead of the step since the last
        // move re-divides it by the *new* scale, snapping the node backwards.
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 200, clientY: 100 }));
      });

      expect(positionOf(node("decisions/a")).x).toBeCloseTo(midDrag.x);
      expect(positionOf(node("decisions/a")).y).toBeCloseTo(midDrag.y);
    });

    it("ignores a right-button press: no drag, and no drawer behind the context menu", () => {
      const onNavigate = vi.fn();
      const { canvas } = renderGraph({ onNavigate });
      const target = node("decisions/a");
      const before = transformOf(target);
      const opts = { ...PRESS, button: 2, buttons: 2, clientX: 100, clientY: 100 };

      act(() => {
        target.dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 220, clientY: 160 }));
        canvas.dispatchEvent(new PointerEvent("pointerup", { ...opts, clientX: 220, clientY: 160 }));
      });

      expect(transformOf(node("decisions/a"))).toBe(before);
      expect(onNavigate).not.toHaveBeenCalled();
    });

    it("declines a second finger instead of letting it steal the drag in progress", () => {
      const { canvas } = renderGraph();
      const originalX = positionOf(node("decisions/a")).x;
      const first = { ...PRESS, clientX: 100, clientY: 100 };
      const second = { ...PRESS, pointerId: 2, isPrimary: false, clientX: 400, clientY: 400 };

      act(() => {
        node("decisions/a").dispatchEvent(new PointerEvent("pointerdown", first));
        node("decisions/b").dispatchEvent(new PointerEvent("pointerdown", second));
        // The first finger keeps moving; it must still own the gesture.
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...first, clientX: 220, clientY: 160 }));
        canvas.dispatchEvent(new PointerEvent("pointerup", { ...first, clientX: 220, clientY: 160 }));
      });

      expect(positionOf(node("decisions/a")).x).toBeCloseTo(originalX + 120);
    });

    it("stops following the cursor when the release happened somewhere it never heard", () => {
      // Pointer capture normally guarantees the release comes back to this
      // canvas. Where it isn't available, the only evidence a drag ended is a
      // move with no button held — without acting on that the node trails the
      // cursor around the screen forever.
      const { canvas } = renderGraph();
      const opts = { ...PRESS, clientX: 100, clientY: 100 };

      act(() => {
        node("decisions/a").dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 200, clientY: 100 }));
      });
      const whenReleased = positionOf(node("decisions/a"));

      act(() => {
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, buttons: 0, clientX: 400, clientY: 300 }));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 600, clientY: 500 }));
      });

      expect(positionOf(node("decisions/a")).x).toBeCloseTo(whenReleased.x);
    });

    it("abandons a cancelled press rather than treating it as a click", () => {
      const onNavigate = vi.fn();
      const { canvas } = renderGraph({ onNavigate });
      const opts = { ...PRESS, clientX: 100, clientY: 100 };

      act(() => {
        node("decisions/a").dispatchEvent(new PointerEvent("pointerdown", opts));
        // The system takes the pointer away — no pointerup ever arrives.
        canvas.dispatchEvent(new PointerEvent("pointercancel", opts));
      });

      expect(onNavigate).not.toHaveBeenCalled();
    });
  });

  describe("pan", () => {
    /** Deliberately *not* the 1000x700 viewBox: at that one size a screen pixel
     *  happens to equal a graph unit, which hides any missing conversion. Real
     *  panes are almost never that size. */
    const PANE_W = 2000;
    const PANE_H = 1400;

    function translateOf(canvas: Element) {
      const t = canvas.querySelector("g")?.getAttribute("transform") ?? "";
      const [x, y] = /translate\(([-\d.]+),([-\d.]+)\)/.exec(t)!.slice(1).map(Number);
      return { x, y };
    }

    it("moves the graph with the cursor, in graph units rather than raw pixels", () => {
      render(<MemoryGraph graph={graph()} />);
      const canvas = screen.getByRole("group", { name: /memory link graph/i });
      canvas.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: PANE_W, height: PANE_H, right: PANE_W, bottom: PANE_H, x: 0, y: 0 }) as DOMRect;
      const before = translateOf(canvas);
      const opts = { ...PRESS, clientX: 100, clientY: 100 };

      act(() => {
        canvas.dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 300, clientY: 240 }));
        canvas.dispatchEvent(new PointerEvent("pointerup", { ...opts, clientX: 300, clientY: 240 }));
      });

      // The pane is twice the viewBox, so a 200x140 pixel drag is a 100x70 unit
      // one. Feeding the pixel delta straight into `translate` (which speaks
      // units) is what made the graph outrun the cursor.
      const after = translateOf(canvas);
      expect(after.x).toBeCloseTo(before.x + 100);
      expect(after.y).toBeCloseTo(before.y + 70);
    });
  });

  it("reports no orphans, roots, leaves or broken links when every memory is linked", () => {
    // Both nodes are well-connected (inbound=1, outbound=1), so no node is
    // a root, orphan, or leaf — the strip should show only memory/link counts.
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
    expect(screen.queryAllByText(wholeText(/^\d+ roots?$/))).toHaveLength(0);
    expect(screen.queryAllByText(wholeText(/^\d+ leaf$/))).toHaveLength(0);
    expect(screen.queryAllByText(wholeText(/^\d+ leaves$/))).toHaveLength(0);
    expect(screen.queryAllByText(wholeText(/^\d+ broken links?$/))).toHaveLength(0);
  });
});
