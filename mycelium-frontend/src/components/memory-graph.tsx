// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { AlertTriangle, ChevronDown, ChevronUp, ExternalLink, Filter, Link2, RotateCcw, Unlink } from "lucide-react";
import type { MemoryGraph as MemoryGraphData, MemoryGraphNode } from "@/lib/api";
import { computeForceLayout, type GraphLayoutEdge, type GraphLayoutNode } from "@/lib/memory-graph-layout";
import { isBrokenLinkError, linkErrorLabel, LINK_ERRORS } from "@/lib/memory-links";
import { Tooltip } from "@/components/ui/tooltip";
import {
  loadPlacements,
  savePlacements,
  type Placements,
  type Point,
} from "@/lib/memory-graph-placements";

interface Props {
  /** Treated as immutable and keyed by identity: a new object reruns the force
   *  layout, drops any filters, and reloads the saved arrangement. Hold it in
   *  state rather than rebuilding it each render. */
  graph: MemoryGraphData;
  /** Opens a memory by key — supplied by whatever owns navigation. */
  onNavigate?: (key: string) => void;
  /** Enables persisting this room's hand-arranged layout. Omit for no persistence. */
  roomName?: string;
  className?: string;
}

const WIDTH = 1000;
const HEIGHT = 700;
const MIN_SCALE = 0.35;
const MAX_SCALE = 3;

/** Pointer travel (screen px) past which a press on a node is a drag, not a
 *  click. Without it, the tremor in an ordinary click would nudge nodes. */
const DRAG_THRESHOLD = 4;

/** Long enough to fold a whole drag into one write, short enough that it lands
 *  well before any realistic reload. */
const SAVE_DEBOUNCE_MS = 250;

// A small, fixed palette, assigned by `colorMapFor` below. The values are theme
// tokens (`globals.css`), so the palette re-tunes itself for the light canvas
// rather than staying at dark-mode brightness.
const NAMESPACE_COLORS = Array.from({ length: 8 }, (_, i) => `var(--graph-ns-${i + 1})`);

const ROOT_NAMESPACE = "(root)";

/** What an edge is filtered by: its relation name when it has one, else its
 *  kind — the same string the tooltip shows, so the legend can't name an edge
 *  one thing and the filter another. */
function edgeTypeOf(edge: { kind: string; relation?: string | null }): string {
  return edge.relation ?? edge.kind;
}

function namespaceOf(key: string): string {
  const slash = key.indexOf("/");
  return slash === -1 ? ROOT_NAMESPACE : key.slice(0, slash);
}

/** Namespace → color, by position in the room's own sorted namespace list.
 *
 *  Not by hashing the name, which was the previous scheme and is wrong for the
 *  job: `context` and `decisions` hash to the same slot, so the two most common
 *  namespaces in any room rendered as the *same* color, indistinguishable and
 *  unfixable by repainting the palette. Assigning by position instead makes a
 *  collision impossible below 9 namespaces, and since the palette is ordered
 *  farthest-apart-first, the handful a real room has land far apart in hue.
 *
 *  The cost is that colors aren't stable across rooms, and adding a namespace
 *  can restripe the ones sorting after it. That's the right trade: the legend
 *  states the mapping on screen, so a color only has to be unambiguous *here*,
 *  and being memorable across rooms was never something the view promised.
 *
 *  Past 8 namespaces the palette wraps and two of them do share a color. The
 *  legend still names every namespace, so the ambiguity is recoverable by
 *  reading rather than silent; a 9th distinct hue would have to come out of the
 *  arc reserved for `--red`/`--yellow` (broken links, orphan nodes), and colliding
 *  with a state color reads as a worse lie than colliding with a sibling. */
function colorMapFor(namespaces: readonly string[]): Map<string, string> {
  return new Map(namespaces.map((ns, i) => [ns, NAMESPACE_COLORS[i % NAMESPACE_COLORS.length]]));
}

function leafName(key: string): string {
  const slash = key.lastIndexOf("/");
  return slash === -1 ? key : key.slice(slash + 1);
}

function nodeRadius(node: MemoryGraphNode): number {
  const degree = node.inbound + node.outbound;
  return Math.min(16, 6 + Math.sqrt(degree) * 3);
}

/** Routes every later move/up for this pointer to one element, so a drag
 *  survives the cursor outrunning the canvas. Optional because jsdom doesn't
 *  implement it on SVG elements. Without it a release outside the canvas is
 *  never delivered, which is why `handlePointerMove` also ends a gesture whose
 *  buttons have gone up — otherwise the node would follow the cursor forever. */
function capturePointer(el: SVGSVGElement | null, pointerId: number): void {
  el?.setPointerCapture?.(pointerId);
}

/** Only the main button of the first pointer drives the canvas.
 *
 *  Without this a right-click both opens the context menu and opens the memory
 *  (a press with no movement is how this view decides a click happened), and a
 *  second finger hijacks the single drag slot, freezing whatever the first one
 *  was moving. */
function isPrimaryPress(e: { button: number; isPrimary: boolean }): boolean {
  return e.button === 0 && e.isPrimary;
}

/** Force-directed view of a room's memory links (#599). Runs the layout once
 *  per graph payload (no live physics), then offers plain SVG pan/zoom, hover
 *  highlighting, drag-to-arrange, and click-to-open — no charting/graph
 *  dependency, so it reuses the app's own design tokens instead of a library's
 *  theme. Because the simulation is already stopped, a drag is a plain
 *  coordinate override rather than a pinned node in a running simulation. */
export function MemoryGraph({ graph, onNavigate, roomName, className }: Props) {
  const layout = useMemo(() => computeForceLayout(graph, { width: WIDTH, height: HEIGHT }), [graph]);

  const namespaces = useMemo(
    () => Array.from(new Set(graph.nodes.map(n => namespaceOf(n.key)))).sort(),
    [graph.nodes],
  );
  const edgeTypes = useMemo(
    () => Array.from(new Set(graph.edges.map(edgeTypeOf))).sort(),
    [graph.edges],
  );
  const colors = useMemo(() => colorMapFor(namespaces), [namespaces]);
  const colorFor = useCallback(
    (ns: string) => colors.get(ns) ?? NAMESPACE_COLORS[0],
    [colors],
  );

  // Filters are held as the *hidden* sets so an unfiltered graph is the empty
  // state, and a namespace or relation that appears later isn't silently
  // excluded for never having been ticked.
  const [hiddenNamespaces, setHiddenNamespaces] = useState<ReadonlySet<string>>(new Set());
  const [hiddenTypes, setHiddenTypes] = useState<ReadonlySet<string>>(new Set());
  const [legendOpen, setLegendOpen] = useState(false);
  const filtered = hiddenNamespaces.size > 0 || hiddenTypes.size > 0;

  // Reset the filters when the graph changes. The guard keeps the same Set
  // identity when nothing was filtered, so every node doesn't re-render.
  const [prevGraph, setPrevGraph] = useState(graph);
  if (prevGraph !== graph) {
    setPrevGraph(graph);
    setHiddenNamespaces(prev => (prev.size === 0 ? prev : new Set()));
    setHiddenTypes(prev => (prev.size === 0 ? prev : new Set()));
  }

  const visibleKeys = useMemo(
    () => new Set(graph.nodes.filter(n => !hiddenNamespaces.has(namespaceOf(n.key))).map(n => n.key)),
    [graph.nodes, hiddenNamespaces],
  );
  // A line is drawn only if its type is shown *and* both endpoints are, so
  // hiding a namespace takes its edges with it rather than leaving them dangling.
  const edgeDrawable = useCallback(
    (e: { source: string; target: string; kind: string; relation?: string | null }) =>
      !hiddenTypes.has(edgeTypeOf(e)) && visibleKeys.has(e.source) && visibleKeys.has(e.target),
    [hiddenTypes, visibleKeys],
  );
  // Counting a *failed* link turns on the source alone. Requiring a visible
  // target would drop every `not_found` from the tally, since its target isn't
  // a memory in this room to begin with — the break is a fact about the memory
  // that wrote the link, which is exactly the one being shown or hidden.
  const brokenAttributable = useCallback(
    (e: { source: string; kind: string; relation?: string | null }) =>
      !hiddenTypes.has(edgeTypeOf(e)) && visibleKeys.has(e.source),
    [hiddenTypes, visibleKeys],
  );

  const visibleNodes = useMemo(() => layout.nodes.filter(n => visibleKeys.has(n.key)), [layout.nodes, visibleKeys]);
  const visibleEdges = useMemo(() => layout.edges.filter(edgeDrawable), [layout.edges, edgeDrawable]);

  // Every count below describes what's on screen, so the strip and the canvas
  // never disagree. "Links" counts drawn resolved arcs; "broken" counts drawn
  // broken arcs. Dead references (not_found targets that aren't nodes) aren't
  // drawn and so don't appear here — they're surfaced by the integrity system
  // (IntegrityBanner in the detail drawer; `mycelium memory --check`).
  const linkCount = useMemo(() => visibleEdges.filter(e => e.resolved).length, [visibleEdges]);
  // A broken arc is only drawn when its target is also a real node, so we
  // derive brokenCount from visibleEdges (the drawn set) rather than from
  // graph.edges (all unresolved references from visible sources). Cross-room
  // references are excluded — they're legitimate syntax, not mistakes.
  const brokenCount = useMemo(
    () => visibleEdges.filter(e => !e.resolved && isBrokenLinkError(e.error)).length,
    [visibleEdges],
  );
  // Cross-room count still comes from all edges (not just drawn), since the
  // cross-room target won't be a node; brokenAttributable narrows to visible sources.
  const unresolvedShown = useMemo(
    () => graph.edges.filter(e => !e.resolved && brokenAttributable(e)),
    [graph.edges, brokenAttributable],
  );
  const crossRoomCount = useMemo(
    () => unresolvedShown.filter(e => !isBrokenLinkError(e.error)).length,
    [unresolvedShown],
  );
  // Graph roles stay facts about the room, not the filter: `inbound`/`outbound`
  // are full-graph counts, so hiding a namespace can't reclassify a node. Only
  // the tallies are narrowed to what's visible.
  //
  // Vocabulary:
  //   orphan — inbound === 0 AND outbound === 0: fully isolated.
  //   root   — inbound === 0 AND outbound > 0:  entry point, nothing links here.
  //   leaf   — inbound > 0  AND outbound === 0: dead end, links arrive but stop.
  const orphanCount = useMemo(
    () => graph.nodes.filter(n => n.inbound === 0 && n.outbound === 0 && visibleKeys.has(n.key)).length,
    [graph.nodes, visibleKeys],
  );
  const rootCount = useMemo(
    () => graph.nodes.filter(n => n.inbound === 0 && n.outbound > 0 && visibleKeys.has(n.key)).length,
    [graph.nodes, visibleKeys],
  );
  const leafCount = useMemo(
    () => graph.nodes.filter(n => n.inbound > 0 && n.outbound === 0 && visibleKeys.has(n.key)).length,
    [graph.nodes, visibleKeys],
  );

  const toggle = useCallback(
    (setter: typeof setHiddenNamespaces, value: string) =>
      setter(prev => {
        const next = new Set(prev);
        if (!next.delete(value)) next.add(value);
        return next;
      }),
    [],
  );
  const clearFilters = useCallback(() => {
    setHiddenNamespaces(new Set());
    setHiddenTypes(new Set());
  }, []);

  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  // Hand-placed node positions, overriding the force layout by key. The
  // simulation has already stopped by the time anything renders, so a drag is
  // just a coordinate override — there is no live physics to pin against.
  const [placed, setPlaced] = useState<Placements>({});
  const svgRef = useRef<SVGSVGElement>(null);
  // `last` is in SVG user space, not client pixels: `view.x/y` feed a
  // `translate()`, so the delta has to be measured in the units translate
  // speaks or the graph slides faster or slower than the cursor.
  //
  // Each move applies the step since the previous one rather than the total
  // since the press, so a zoom landing mid-gesture just changes the scale of
  // what follows instead of retroactively rescaling everything already moved.
  const panState = useRef<{ pointerId: number; last: Point } | null>(null);
  // `startX/startY` stay in client pixels because they only feed the "was this a
  // drag or a click?" threshold, which is a screen-distance question; `last` is
  // the user-space step baseline, as on `panState`.
  const nodeDrag = useRef<{
    pointerId: number;
    key: string;
    startX: number;
    startY: number;
    last: Point;
    origin: Point;
    moved: boolean;
  } | null>(null);

  // Read by the deferred writes below, so they always persist the newest
  // arrangement rather than the one captured when their timer was armed.
  const latestPlaced = useRef(placed);
  useLayoutEffect(() => { latestPlaced.current = placed; }, [placed]);

  // Only a drag or a reset may write. Persisting on any change to `placed`
  // instead — mirroring state outward — silently wiped the saved arrangement
  // under StrictMode, which Next enables in dev: its mount-time cleanup pass
  // fired the unmount flush below while `placed` was still the pre-hydration
  // empty map, storing that over the real one. Nothing about hydration is worth
  // persisting anyway, since it came from the store to begin with.
  const dirty = useRef(false);

  // Hydrated in an effect rather than during render, since reading storage
  // inline would desync SSR markup. A *layout* effect specifically: a plain one
  // paints the force positions first and snaps to the saved arrangement a frame
  // later, which reads as a flinch on every load. Safe here because this
  // component only ever mounts client-side — its parent renders a loading state
  // until the graph fetch resolves — so the server never reaches this.
  //
  // Re-runs when the payload changes, pruned to the nodes that actually exist
  // now, so a renamed or deleted memory drops its position instead of stranding
  // it.
  useLayoutEffect(() => {
    dirty.current = false;
    if (!roomName) {
      // Placements are read from storage, so they land in a layout effect —
      // before the new layout's first paint.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPlaced({});
      return;
    }
    setPlaced(loadPlacements(roomName, new Set(graph.nodes.map(n => n.key))));
  }, [graph, roomName]);

  // Debounced because a drag sets `placed` on every pointermove and
  // `localStorage` writes are synchronous — without this, one gesture would
  // mean a hundred blocking writes instead of one.
  useEffect(() => {
    if (!roomName || !dirty.current) return undefined;
    const timer = setTimeout(() => savePlacements(roomName, latestPlaced.current), SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [placed, roomName]);

  // The debounce would otherwise swallow an arrangement made immediately before
  // navigating away, since unmounting clears the pending timer.
  //
  // Declared *after* the layout effect that loads a room's placements, and that
  // order is load-bearing: layout effects clean up before passive ones, so on a
  // room change the loader has already cleared `dirty` by the time this cleanup
  // reads `latestPlaced` — which by then holds the incoming room's positions.
  // Reordering these, or demoting the loader to a plain effect, would write one
  // room's arrangement into another's key.
  useEffect(() => {
    if (!roomName) return undefined;
    return () => {
      if (dirty.current) savePlacements(roomName, latestPlaced.current);
    };
  }, [roomName]);

  const positions = useMemo(() => {
    const map = new Map<string, Point>();
    for (const n of layout.nodes) map.set(n.key, placed[n.key] ?? { x: n.x, y: n.y });
    return map;
  }, [layout.nodes, placed]);

  // Walks the *drawn* edges, not the whole payload: highlighting a neighbor
  // reached through a filtered-out edge would assert a connection the canvas
  // isn't showing.
  const neighbors = useMemo(() => {
    // A node that gets filtered away under a stationary cursor fires no
    // mouseleave, so `hovered` can outlive what it named. Treating that as "not
    // hovering" keeps a stale key from dimming the whole canvas with nothing
    // highlighted to explain why.
    if (!hovered || !visibleKeys.has(hovered)) return null;
    const set = new Set<string>([hovered]);
    for (const e of visibleEdges) {
      if (e.source === hovered) set.add(e.target);
      else if (e.target === hovered) set.add(e.source);
    }
    return set;
  }, [hovered, visibleEdges, visibleKeys]);

  /** Client coordinates → the SVG's own user space (pre pan/zoom transform). */
  const toSvgPoint = useCallback((clientX: number, clientY: number): Point => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    // The real CTM accounts for the letterboxing `viewBox` + `preserveAspect
    // Ratio` introduce when the pane's aspect differs from 1000x700, which the
    // naive bounding-rect ratio below gets wrong. jsdom implements neither
    // getScreenCTM nor DOMPoint, hence the fallback rather than a hard require.
    const ctm = svg.getScreenCTM?.();
    if (ctm && typeof DOMPoint !== "undefined") {
      const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
      return { x: p.x, y: p.y };
    }
    const rect = svg.getBoundingClientRect();
    return {
      x: ((clientX - rect.left) / rect.width) * WIDTH,
      y: ((clientY - rect.top) / rect.height) * HEIGHT,
    };
  }, []);

  // Wheel-zoom is wired natively rather than through `onWheel`: React registers
  // wheel listeners as passive, so a `preventDefault()` inside a React handler
  // is a no-op that only earns a console warning — and the browser would keep
  // its own ctrl+wheel page zoom while you tried to zoom the graph.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const onWheel = (e: globalThis.WheelEvent) => {
      e.preventDefault();
      const { x: cx, y: cy } = toSvgPoint(e.clientX, e.clientY);
      setView(prev => {
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        const nextScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * factor));
        // Keep the point under the cursor fixed so zooming feels anchored
        // rather than sliding the graph around.
        const px = (cx - prev.x) / prev.scale;
        const py = (cy - prev.y) / prev.scale;
        return { scale: nextScale, x: cx - px * nextScale, y: cy - py * nextScale };
      });
    };

    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [toSvgPoint]);

  const handlePointerDown = useCallback(
    (e: PointerEvent<SVGSVGElement>) => {
      if (e.target !== svgRef.current) return; // a node owns its own press
      if (!isPrimaryPress(e)) return;
      panState.current = { pointerId: e.pointerId, last: toSvgPoint(e.clientX, e.clientY) };
      capturePointer(svgRef.current, e.pointerId);
    },
    [toSvgPoint],
  );

  const beginNodeDrag = useCallback(
    (key: string, e: PointerEvent<SVGGElement>) => {
      if (!isPrimaryPress(e)) return;
      const origin = positions.get(key);
      if (!origin) return;
      nodeDrag.current = {
        pointerId: e.pointerId,
        key,
        startX: e.clientX,
        startY: e.clientY,
        last: toSvgPoint(e.clientX, e.clientY),
        origin,
        moved: false,
      };
      // Captured on the <svg>, not the node, so the pointer keeps reporting to
      // one handler even when it outruns the circle it grabbed.
      capturePointer(svgRef.current, e.pointerId);
    },
    [positions, toSvgPoint],
  );

  /** Drops whatever gesture this pointer owned, without activating anything. */
  const abandonGesture = useCallback((pointerId: number) => {
    if (nodeDrag.current?.pointerId === pointerId) nodeDrag.current = null;
    if (panState.current?.pointerId === pointerId) panState.current = null;
  }, []);

  const handlePointerMove = useCallback(
    (e: PointerEvent<SVGSVGElement>) => {
      // A move with nothing held down means this pointer's release happened
      // somewhere the canvas never heard about (no pointer capture, or it was
      // lost). Dropping the gesture here stops a node from trailing a cursor
      // that isn't pressing anything.
      if (e.buttons === 0) {
        abandonGesture(e.pointerId);
        return;
      }

      const drag = nodeDrag.current;
      if (drag && drag.pointerId === e.pointerId) {
        if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > DRAG_THRESHOLD) {
          drag.moved = true;
        }
        if (!drag.moved) return;
        const to = toSvgPoint(e.clientX, e.clientY);
        // The nodes live inside the pan/zoom <g>, so a delta measured in SVG
        // space has to be divided back out by the zoom to stay under the cursor.
        const dx = (to.x - drag.last.x) / view.scale;
        const dy = (to.y - drag.last.y) / view.scale;
        drag.last = to;
        dirty.current = true;
        setPlaced(prev => {
          const from = prev[drag.key] ?? drag.origin;
          return { ...prev, [drag.key]: { x: from.x + dx, y: from.y + dy } };
        });
        return;
      }

      const pan = panState.current;
      if (!pan || pan.pointerId !== e.pointerId) return;
      // Measured in user space, and *not* divided by the zoom: `translate` runs
      // before `scale` in the transform, so it already speaks parent units.
      const to = toSvgPoint(e.clientX, e.clientY);
      const dx = to.x - pan.last.x;
      const dy = to.y - pan.last.y;
      pan.last = to;
      setView(prev => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
    },
    [abandonGesture, toSvgPoint, view.scale],
  );

  // Opening is decided here on pointerup, not by a `click` handler on the node.
  // Taking pointer capture retargets the browser's follow-up `click` to the
  // capture element (the <svg>), so a node-level onClick simply never fires
  // once a press has been captured — the press sequence has to own the decision.
  const endDrag = useCallback(
    (e: PointerEvent<SVGSVGElement>) => {
      const drag = nodeDrag.current;
      if (drag?.pointerId === e.pointerId) {
        nodeDrag.current = null;
        // `visibleKeys` because a filter applied mid-press can retire the node
        // under the finger, and opening a memory the canvas is busy hiding reads
        // as the wrong one having been clicked.
        if (!drag.moved && visibleKeys.has(drag.key)) onNavigate?.(drag.key);
      }
      if (panState.current?.pointerId === e.pointerId) panState.current = null;
    },
    [onNavigate, visibleKeys],
  );

  // A cancelled pointer is an abandoned gesture, not a completed one: the system
  // took the pointer away (touch handed to a browser gesture, device removed),
  // so routing it through `endDrag` would open a memory the reader never
  // released on.
  const cancelDrag = useCallback(
    (e: PointerEvent<SVGSVGElement>) => abandonGesture(e.pointerId),
    [abandonGesture],
  );

  const hasPlacements = Object.keys(placed).length > 0;

  return (
    <div className={`flex h-full min-h-0 flex-col overflow-hidden ${className ?? ""}`}>
      {/* Summary strip — derived from the same payload the graph draws, so it
          never has to make a second integrity call. */}
      <div className="flex flex-shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-paper px-5 py-3 text-label text-muted-foreground">
        <span>
          <span className="font-semibold tabular text-text">{visibleKeys.size}</span> memor
          {visibleKeys.size === 1 ? "y" : "ies"}
          {filtered && <span className="text-faint"> of {graph.nodes.length}</span>}
        </span>
        <span>
          <span className="font-semibold tabular text-text">{linkCount}</span> link
          {linkCount === 1 ? "" : "s"}
        </span>
        {orphanCount > 0 && (
          <Tooltip content="Fully isolated — no inbound or outbound links" side="bottom">
            <span
              className="flex items-center gap-1 text-yellow"
              aria-description="Fully isolated — no inbound or outbound links"
            >
              <Unlink className="size-3.5" />
              <span className="font-semibold tabular">{orphanCount}</span> orphan{orphanCount === 1 ? "" : "s"}
            </span>
          </Tooltip>
        )}
        {rootCount > 0 && (
          <Tooltip content="Entry points — nothing links here yet" side="bottom">
            <span
              className="flex items-center gap-1 text-muted-foreground"
              aria-description="Entry points — nothing links here yet"
            >
              <span className="font-semibold tabular">{rootCount}</span> root{rootCount === 1 ? "" : "s"}
            </span>
          </Tooltip>
        )}
        {leafCount > 0 && (
          <Tooltip content="Dead ends — links arrive but go no further" side="bottom">
            <span
              className="flex items-center gap-1 text-muted-foreground"
              aria-description="Dead ends — links arrive but go no further"
            >
              <span className="font-semibold tabular">{leafCount}</span> lea{leafCount === 1 ? "f" : "ves"}
            </span>
          </Tooltip>
        )}
        {brokenCount > 0 && (
          <span className="flex items-center gap-1 text-red">
            <AlertTriangle className="size-3.5" />
            <span className="font-semibold tabular">{brokenCount}</span> broken link{brokenCount === 1 ? "" : "s"}
          </span>
        )}
        {crossRoomCount > 0 && (
          <Tooltip content={LINK_ERRORS.cross_room} side="bottom">
            <span
              className="flex items-center gap-1 text-muted-foreground"
              aria-description={LINK_ERRORS.cross_room}
            >
              <ExternalLink className="size-3.5" />
              <span className="font-semibold tabular">{crossRoomCount}</span> cross-room
            </span>
          </Tooltip>
        )}
        <div className="ml-auto flex items-center gap-1">
          {filtered && (
            <Tooltip content="Show every namespace and link type again" side="bottom" align="end">
              <button
                onClick={clearFilters}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-micro font-medium text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
              >
                <Filter className="size-3.5" />
                Clear filters
              </button>
            </Tooltip>
          )}
          {hasPlacements && (
            <Tooltip
              content="Put every hand-moved memory back where the force layout placed it, and forget the saved arrangement"
              side="bottom"
              align="end"
            >
              <button
                onClick={() => {
                  dirty.current = true;
                  setPlaced({});
                }}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-micro font-medium text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
              >
                <RotateCcw className="size-3.5" />
                Reset layout
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-full w-full touch-none bg-bg"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={cancelDrag}
          // `group`, not `img`: ARIA treats an `img`'s descendants as
          // presentational, which would hide every node button below from
          // assistive tech.
          role="group"
          aria-label={`Memory link graph: ${visibleKeys.size} memories, ${linkCount} links`}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
            {/* Endpoints come from `positions`, not the layout's baked x1/y1 —
                that's what keeps an edge attached while its node is dragged. */}
            {visibleEdges.map((edge, i) => {
              const from = positions.get(edge.source);
              const to = positions.get(edge.target);
              if (!from || !to) return null;
              return (
                <GraphEdgeLine
                  key={i}
                  edge={edge}
                  from={from}
                  to={to}
                  dimmed={neighbors !== null && !(neighbors.has(edge.source) && neighbors.has(edge.target))}
                />
              );
            })}
            {visibleNodes.map(node => (
              <GraphNodeDot
                key={node.key}
                node={node}
                color={colorFor(namespaceOf(node.key))}
                at={positions.get(node.key) ?? node}
                dimmed={neighbors !== null && !neighbors.has(node.key)}
                onHover={setHovered}
                onNavigate={onNavigate}
                onDragStart={beginNodeDrag}
              />
            ))}
          </g>
        </svg>

        {visibleKeys.size === 0 && (
          // Blames the filter only when a filter is what emptied the canvas.
          // `MemoryGraph` is exported on its own, so it can also be handed a
          // payload with no nodes at all.
          <p
            role="status"
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-label text-muted-foreground"
          >
            {graph.nodes.length === 0 ? "Nothing to show." : "Every namespace is hidden — nothing to show."}
          </p>
        )}

        {/* Legend — floats over the canvas, outside the pan/zoom transform, and
            doubles as the filter. Collapsed to a pill tab by default; click the
            tab to expand, click again (or the header) to collapse. */}
        <div className="absolute bottom-3 left-3 flex flex-col items-start gap-0">
          {legendOpen && (
            <div className="mb-0 flex flex-col gap-1 rounded-t-lg border border-b-0 border-border bg-paper/90 px-3 py-2 text-micro text-muted-foreground shadow-sm backdrop-blur-sm">
              <div className="text-faint">namespace</div>
              {namespaces.map(ns => {
                const hidden = hiddenNamespaces.has(ns);
                return (
                  <Tooltip key={ns} content={hidden ? `Show ${ns}` : `Hide ${ns}`} side="right">
                    <button
                      onClick={() => toggle(setHiddenNamespaces, ns)}
                      aria-pressed={!hidden}
                      aria-label={hidden ? `Show ${ns}` : `Hide ${ns}`}
                      className={`flex items-center gap-1.5 rounded px-1 py-0.5 text-left transition-colors hover:bg-hairline ${
                        hidden ? "opacity-40" : ""
                      }`}
                    >
                      <span
                        className="size-2 flex-shrink-0 rounded-full"
                        style={{ background: hidden ? "transparent" : colorFor(ns), boxShadow: `inset 0 0 0 1px ${colorFor(ns)}` }}
                      />
                      <span className={`font-mono ${hidden ? "line-through" : ""}`}>{ns}</span>
                    </button>
                  </Tooltip>
                );
              })}

              {edgeTypes.length > 1 && (
                <>
                  <div className="mt-1 border-t border-border pt-1 text-faint">link type</div>
                  {edgeTypes.map(type => {
                    const hidden = hiddenTypes.has(type);
                    return (
                      <Tooltip
                        key={type}
                        content={hidden ? `Show ${type} edges` : `Hide ${type} edges`}
                        side="right"
                      >
                        <button
                          onClick={() => toggle(setHiddenTypes, type)}
                          aria-pressed={!hidden}
                          aria-label={hidden ? `Show ${type} edges` : `Hide ${type} edges`}
                          className={`flex items-center gap-1.5 rounded px-1 py-0.5 text-left transition-colors hover:bg-hairline ${
                            hidden ? "opacity-40" : ""
                          }`}
                        >
                          <Link2 className="size-3 flex-shrink-0" />
                          <span className={`font-mono ${hidden ? "line-through" : ""}`}>{type}</span>
                        </button>
                      </Tooltip>
                    );
                  })}
                </>
              )}

              <div className="mt-1 flex items-center gap-1.5 border-t border-border pt-1">
                <span className="size-2 flex-shrink-0 rounded-full border-2 border-dashed border-yellow" />
                orphan (no connections)
              </div>
              <div className="flex items-center gap-1.5">
                <span className="size-2 flex-shrink-0 rounded-full border-2 border-dashed border-muted-foreground" />
                leaf (links arrive, go no further)
              </div>
              <div className="flex items-center gap-1.5">
                <Link2 className="size-3" />
                solid = link · dashed = relation
              </div>
              <div className="flex items-center gap-1.5 text-red">
                <span className="h-px w-3 flex-shrink-0 border-t border-dashed border-red" />
                broken link between two real memories
              </div>
              <div className="mt-1 border-t border-border pt-1">drag a memory to arrange · click to open</div>
            </div>
          )}
          <button
            onClick={() => setLegendOpen(o => !o)}
            aria-expanded={legendOpen}
            aria-label={legendOpen ? "Collapse legend" : "Expand legend"}
            className={`flex items-center gap-1 rounded-b-lg border border-border bg-paper/90 px-3 py-1 text-micro font-semibold uppercase tracking-wide text-faint shadow-sm backdrop-blur-sm transition-colors hover:bg-hairline hover:text-text ${
              legendOpen ? "" : "rounded-t-lg"
            }`}
          >
            Key
            {legendOpen ? <ChevronDown className="size-3" /> : <ChevronUp className="size-3" />}
          </button>
        </div>
      </div>
    </div>
  );
}

function GraphEdgeLine({ edge, from, to, dimmed }: { edge: GraphLayoutEdge; from: Point; to: Point; dimmed: boolean }) {
  // A relation is dashed to read as "typed, not a plain reference"; a broken
  // edge is dashed *and* red. Both ends are real memories here — only the link
  // between them failed — so it's drawn rather than quietly omitted.
  const dashed = edge.kind === "relation" || !edge.resolved;
  const label = edge.resolved ? (edge.relation ?? edge.kind) : linkErrorLabel(edge.error);
  return (
    <line
      x1={from.x}
      y1={from.y}
      x2={to.x}
      y2={to.y}
      stroke={edge.resolved ? "var(--border2)" : "var(--red)"}
      strokeWidth={dimmed ? 1 : 1.5}
      strokeDasharray={dashed ? "4 3" : undefined}
      opacity={dimmed ? 0.15 : 0.6}
    >
      <title>{`${edge.source} → ${edge.target} (${label})`}</title>
    </line>
  );
}

function GraphNodeDot({
  node,
  color,
  at,
  dimmed,
  onHover,
  onNavigate,
  onDragStart,
}: {
  node: GraphLayoutNode;
  /** Resolved namespace fill — the mapping is room-wide, so the parent owns it. */
  color: string;
  /** Where to draw — the hand-placed position if there is one, else the layout's. */
  at: Point;
  dimmed: boolean;
  onHover: (key: string | null) => void;
  /** Keyboard activation only; a pointer press is resolved by the canvas, which
   *  is the one place that knows whether the press turned into a drag. */
  onNavigate?: (key: string) => void;
  onDragStart: (key: string, e: PointerEvent<SVGGElement>) => void;
}) {
  const radius = nodeRadius(node);
  const isOrphan = node.inbound === 0 && node.outbound === 0;
  const isLeaf = node.inbound > 0 && node.outbound === 0;
  // roots (inbound=0, outbound>0) get no special border — entry points are intentional.

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<SVGGElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onNavigate?.(node.key);
      }
    },
    [node.key, onNavigate],
  );
  const handlePointerDown = useCallback(
    (e: PointerEvent<SVGGElement>) => onDragStart(node.key, e),
    [node.key, onDragStart],
  );

  return (
    <g
      transform={`translate(${at.x},${at.y})`}
      opacity={dimmed ? 0.25 : 1}
      onMouseEnter={() => onHover(node.key)}
      onMouseLeave={() => onHover(null)}
      // Focus highlights too, so tabbing through the graph reveals each memory's
      // neighbours the way hovering does rather than only moving a focus ring.
      onFocus={() => onHover(node.key)}
      onBlur={() => onHover(null)}
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Open ${node.key}`}
      className="cursor-grab active:cursor-grabbing"
    >
      <circle
        r={radius}
        fill={color}
        stroke={isOrphan ? "var(--yellow)" : isLeaf ? "var(--muted-foreground)" : "var(--paper)"}
        strokeWidth={isOrphan || isLeaf ? 2 : 1.5}
        strokeDasharray={isOrphan ? "3 2" : isLeaf ? "2 3" : undefined}
      >
        <title>{node.key}</title>
      </circle>
      <text
        x={radius + 4}
        y={4}
        fontSize={11}
        fill="var(--muted-foreground)"
        className="select-none"
        style={{ paintOrder: "stroke", stroke: "var(--bg)", strokeWidth: 3 }}
      >
        {leafName(node.key)}
      </text>
    </g>
  );
}
