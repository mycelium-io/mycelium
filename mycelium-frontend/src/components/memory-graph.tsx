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
import { AlertTriangle, ExternalLink, Link2, RotateCcw, Unlink } from "lucide-react";
import type { MemoryGraph as MemoryGraphData, MemoryGraphNode } from "@/lib/api";
import { computeForceLayout, type GraphLayoutEdge, type GraphLayoutNode } from "@/lib/memory-graph-layout";
import { isBrokenLinkError, linkErrorLabel, LINK_ERRORS } from "@/lib/memory-links";
import {
  loadPlacements,
  savePlacements,
  type Placements,
  type Point,
} from "@/lib/memory-graph-placements";

interface Props {
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

// A small, fixed, deterministic palette: namespaces are colored by a stable
// hash of their name rather than an enumerated list, so a brand-new
// top-level folder gets a color without this file needing to know about it.
// The values are theme tokens (`globals.css`), so the palette re-tunes itself
// for the light canvas rather than staying at dark-mode brightness.
const NAMESPACE_COLORS = Array.from({ length: 8 }, (_, i) => `var(--graph-ns-${i + 1})`);

const ROOT_NAMESPACE = "(root)";

function namespaceOf(key: string): string {
  const slash = key.indexOf("/");
  return slash === -1 ? ROOT_NAMESPACE : key.slice(0, slash);
}

function colorFor(namespace: string): string {
  let hash = 0;
  for (let i = 0; i < namespace.length; i++) hash = (hash * 31 + namespace.charCodeAt(i)) >>> 0;
  return NAMESPACE_COLORS[hash % NAMESPACE_COLORS.length];
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
 *  implement it on SVG elements; losing it only costs that robustness. */
function capturePointer(el: SVGSVGElement | null, pointerId: number): void {
  el?.setPointerCapture?.(pointerId);
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

  // "Links" counts what actually resolves; a broken edge is reported on its own
  // terms beside it, never folded into the working total.
  const linkCount = useMemo(() => layout.edges.filter(e => e.resolved).length, [layout.edges]);
  // Cross-room references are reported apart from breakage: they're legitimate
  // syntax that just can't resolve room-locally, so calling them broken would
  // fault a room for doing something correct.
  const brokenCount = useMemo(
    () => graph.edges.filter(e => !e.resolved && isBrokenLinkError(e.error)).length,
    [graph.edges],
  );
  const crossRoomCount = useMemo(
    () => graph.edges.filter(e => !e.resolved && !isBrokenLinkError(e.error)).length,
    [graph.edges],
  );
  const orphanCount = useMemo(() => graph.nodes.filter(n => n.inbound === 0).length, [graph.nodes]);

  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  // Hand-placed node positions, overriding the force layout by key. The
  // simulation has already stopped by the time anything renders, so a drag is
  // just a coordinate override — there is no live physics to pin against.
  const [placed, setPlaced] = useState<Placements>({});
  const svgRef = useRef<SVGSVGElement>(null);
  const panState = useRef<{ pointerId: number; startX: number; startY: number; viewX: number; viewY: number } | null>(
    null,
  );
  const nodeDrag = useRef<
    { pointerId: number; key: string; startX: number; startY: number; origin: Point; moved: boolean } | null
  >(null);

  // Read by the deferred writes below, so they always persist the newest
  // arrangement rather than the one captured when their timer was armed.
  const latestPlaced = useRef(placed);
  latestPlaced.current = placed;

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

  const neighbors = useMemo(() => {
    if (!hovered) return null;
    const set = new Set<string>([hovered]);
    for (const e of layout.edges) {
      if (e.source === hovered) set.add(e.target);
      else if (e.target === hovered) set.add(e.source);
    }
    return set;
  }, [hovered, layout.edges]);

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
      panState.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, viewX: view.x, viewY: view.y };
      capturePointer(svgRef.current, e.pointerId);
    },
    [view.x, view.y],
  );

  const beginNodeDrag = useCallback(
    (key: string, e: PointerEvent<SVGGElement>) => {
      const origin = positions.get(key);
      if (!origin) return;
      nodeDrag.current = { pointerId: e.pointerId, key, startX: e.clientX, startY: e.clientY, origin, moved: false };
      // Captured on the <svg>, not the node, so the pointer keeps reporting to
      // one handler even when it outruns the circle it grabbed.
      capturePointer(svgRef.current, e.pointerId);
    },
    [positions],
  );

  const handlePointerMove = useCallback(
    (e: PointerEvent<SVGSVGElement>) => {
      const drag = nodeDrag.current;
      if (drag && drag.pointerId === e.pointerId) {
        if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > DRAG_THRESHOLD) {
          drag.moved = true;
        }
        if (!drag.moved) return;
        const from = toSvgPoint(drag.startX, drag.startY);
        const to = toSvgPoint(e.clientX, e.clientY);
        // The nodes live inside the pan/zoom <g>, so a delta measured in SVG
        // space has to be divided back out by the zoom to stay under the cursor.
        const dx = (to.x - from.x) / view.scale;
        const dy = (to.y - from.y) / view.scale;
        dirty.current = true;
        setPlaced(prev => ({ ...prev, [drag.key]: { x: drag.origin.x + dx, y: drag.origin.y + dy } }));
        return;
      }

      const pan = panState.current;
      if (!pan || pan.pointerId !== e.pointerId) return;
      setView(prev => ({ ...prev, x: pan.viewX + (e.clientX - pan.startX), y: pan.viewY + (e.clientY - pan.startY) }));
    },
    [toSvgPoint, view.scale],
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
        if (!drag.moved) onNavigate?.(drag.key);
      }
      if (panState.current?.pointerId === e.pointerId) panState.current = null;
    },
    [onNavigate],
  );

  const hasPlacements = Object.keys(placed).length > 0;

  return (
    <div className={`flex h-full min-h-0 flex-col overflow-hidden ${className ?? ""}`}>
      {/* Summary strip — derived from the same payload the graph draws, so it
          never has to make a second integrity call. */}
      <div className="flex flex-shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-paper px-5 py-3 text-label text-muted-foreground">
        <span>
          <span className="font-semibold tabular text-text">{graph.nodes.length}</span> memor
          {graph.nodes.length === 1 ? "y" : "ies"}
        </span>
        <span>
          <span className="font-semibold tabular text-text">{linkCount}</span> link
          {linkCount === 1 ? "" : "s"}
        </span>
        {orphanCount > 0 && (
          <span className="flex items-center gap-1 text-yellow">
            <Unlink className="size-3.5" />
            <span className="font-semibold tabular">{orphanCount}</span> orphan{orphanCount === 1 ? "" : "s"}
          </span>
        )}
        {brokenCount > 0 && (
          <span className="flex items-center gap-1 text-red">
            <AlertTriangle className="size-3.5" />
            <span className="font-semibold tabular">{brokenCount}</span> broken link{brokenCount === 1 ? "" : "s"}
          </span>
        )}
        {crossRoomCount > 0 && (
          <span
            className="flex items-center gap-1 text-muted-foreground"
            title={LINK_ERRORS.cross_room}
          >
            <ExternalLink className="size-3.5" />
            <span className="font-semibold tabular">{crossRoomCount}</span> cross-room
          </span>
        )}
        {hasPlacements && (
          <button
            onClick={() => {
              dirty.current = true;
              setPlaced({});
            }}
            className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-micro font-medium text-accent transition-colors hover:bg-hairline"
            title="Put every hand-moved memory back where the force layout placed it, and forget the saved arrangement"
          >
            <RotateCcw className="size-3.5" />
            Reset layout
          </button>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-full w-full touch-none bg-bg"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          // `group`, not `img`: ARIA treats an `img`'s descendants as
          // presentational, which would hide every node button below from
          // assistive tech.
          role="group"
          aria-label={`Memory link graph: ${graph.nodes.length} memories, ${linkCount} links`}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
            {/* Endpoints come from `positions`, not the layout's baked x1/y1 —
                that's what keeps an edge attached while its node is dragged. */}
            {layout.edges.map((edge, i) => {
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
            {layout.nodes.map(node => (
              <GraphNodeDot
                key={node.key}
                node={node}
                at={positions.get(node.key) ?? node}
                dimmed={neighbors !== null && !neighbors.has(node.key)}
                onHover={setHovered}
                onNavigate={onNavigate}
                onDragStart={beginNodeDrag}
              />
            ))}
          </g>
        </svg>

        {/* Legend — floats over the canvas, outside the pan/zoom transform. */}
        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1 rounded-lg border border-border bg-paper/90 px-3 py-2 text-micro text-muted-foreground shadow-sm backdrop-blur-sm">
          <div className="mb-0.5 text-micro font-semibold uppercase tracking-wide text-faint">Key</div>
          <div className="text-faint">namespace</div>
          {namespaces.map(ns => (
            <div key={ns} className="flex items-center gap-1.5">
              <span className="size-2 flex-shrink-0 rounded-full" style={{ background: colorFor(ns) }} />
              <span className="font-mono">{ns}</span>
            </div>
          ))}
          <div className="mt-1 flex items-center gap-1.5 border-t border-border pt-1">
            <span className="size-2 flex-shrink-0 rounded-full border border-dashed border-yellow" />
            orphan (nothing links here)
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
  at,
  dimmed,
  onHover,
  onNavigate,
  onDragStart,
}: {
  node: GraphLayoutNode;
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
  const orphan = node.inbound === 0;
  const ns = namespaceOf(node.key);

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
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Open ${node.key}`}
      style={{ cursor: "grab" }}
    >
      <circle
        r={radius}
        fill={colorFor(ns)}
        stroke={orphan ? "var(--yellow)" : "var(--paper)"}
        strokeWidth={orphan ? 2 : 1.5}
        strokeDasharray={orphan ? "3 2" : undefined}
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
