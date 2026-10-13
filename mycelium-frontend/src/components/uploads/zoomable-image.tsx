// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type PointerEvent, type Ref } from "react";
import { Minus, Plus } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import {
  centerOn,
  fitView,
  inView,
  isFit,
  maxScale,
  panBy,
  readout,
  ready,
  stageOf,
  toggleAt,
  zoomAt,
  ZOOM_STEP,
  type Point,
  type Size,
  type Stage,
  type View,
} from "@/lib/zoom";
import { cn } from "@/lib/utils";

/** What the preview window asks of the image for its keys. */
export interface ZoomKeys {
  /** Act on a key, and say whether it was used (+, −, 0, and arrows while zoomed). */
  key: (key: string) => boolean;
}

/** An arrow key moves this share of the frame. */
const PAN_STEP = 0.1;

/** A press that moves no further than this many pixels is a click, not a drag. */
const CLICK_SLOP = 4;

/** The minimap fades after the pointer has been still this long. */
const MINIMAP_IDLE_MS = 2000;

/** The minimap's longest side, in pixels. */
const MINIMAP_SIZE = 160;

const NONE: Size = { width: 0, height: 0 };

/**
 * An image in a frame that zooms and pans the way image viewers do.
 *
 * The frame fills the space it's given (in the preview window, nearly the
 * whole window), whatever the image's shape. The image opens fitted inside it,
 * whole and centered. A click zooms in to 100% at the point clicked, and a
 * click while zoomed goes back to fit (a double-click counts as one click).
 * Zoomed in, the image fills the frame on both axes, so a tall screenshot
 * fills its width and you drag down it; a side still smaller than the frame
 * stays centered, and the image never pans into empty space. The wheel or a
 * pinch zooms around the pointer, a two-finger scroll pans, and the window
 * passes its keys on through `ref`. While zoomed in, a minimap in the corner
 * shows the part in view and moves it when dragged. The readout under the
 * frame says how far in it is, with − and + beside it, and goes back to fit
 * when clicked.
 */
export function ZoomableImage({ src, alt, ref }: { src: string; alt: string; ref?: Ref<ZoomKeys> }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [frame, setFrame] = useState<Size>(NONE);
  const [natural, setNatural] = useState<Size>(NONE);
  const stage = useMemo(() => stageOf(frame, natural), [frame, natural]);
  // Null is fit: whatever fit is for the frame as it stands, so a new window
  // size refits rather than leaving a view measured against the old one.
  const [zoomed, setZoomed] = useState<View | null>(null);
  const view = zoomed ?? fitView(stage);
  const [dragging, setDragging] = useState(false);
  const press = useRef<{ id: number; startX: number; startY: number; x: number; y: number; moved: boolean } | null>(null);
  // The press that ended last was a drag, so the click that follows it isn't one.
  const endedDrag = useRef(false);

  /** Change the view from the one shown, as fit or zoomed. */
  const update = useCallback(
    (next: (v: View, st: Stage) => View) =>
      setZoomed((z) => {
        const v = next(z ?? fitView(stage), stage);
        return isFit(v) ? null : v;
      }),
    [stage],
  );

  // The minimap shows while the pointer moves, and fades once it's been still.
  const [awake, setAwake] = useState(true);
  const sleep = useRef<ReturnType<typeof setTimeout>>(undefined);
  const wake = useCallback(() => {
    setAwake(true);
    clearTimeout(sleep.current);
    sleep.current = setTimeout(() => setAwake(false), MINIMAP_IDLE_MS);
  }, []);
  useEffect(() => () => clearTimeout(sleep.current), []);
  // The wheel listener is attached once; it reads the latest of these.
  const latest = useRef({ view, stage, update });
  useEffect(() => {
    latest.current = { view, stage, update };
  });

  const measureImage = () => {
    const img = imgRef.current;
    if (img) setNatural({ width: img.naturalWidth, height: img.naturalHeight });
  };

  // The frame's size is the window's, so it's watched; a change refits. An
  // image already loaded (from the cache) fired its load before this.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const measure = () => {
      setFrame((was) =>
        was.width === el.clientWidth && was.height === el.clientHeight ? was : { width: el.clientWidth, height: el.clientHeight },
      );
      setZoomed(null);
    };
    measure();
    if (imgRef.current?.complete) measureImage();
    if (typeof ResizeObserver === "undefined") return;
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    return () => seen.disconnect();
  }, []);

  const center = (): Point => ({ x: stage.frame.width / 2, y: stage.frame.height / 2 });
  const zoomBy = (factor: number, point: Point = center()) => update((v, st) => zoomAt(v, v.scale * factor, point, st));

  useImperativeHandle(ref, () => ({
    key(key: string) {
      wake();
      if (key === "+" || key === "=") {
        zoomBy(ZOOM_STEP);
      } else if (key === "-" || key === "_") {
        zoomBy(1 / ZOOM_STEP);
      } else if (key === "0") {
        setZoomed(null);
      } else if (key.startsWith("Arrow") && !isFit(view)) {
        const dx = stage.frame.width * PAN_STEP;
        const dy = stage.frame.height * PAN_STEP;
        const [mx, my] = { ArrowLeft: [dx, 0], ArrowRight: [-dx, 0], ArrowUp: [0, dy], ArrowDown: [0, -dy] }[key] ?? [0, 0];
        update((v, st) => panBy(v, mx, my, st));
      } else {
        return false;
      }
      return true;
    },
  }));

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const { view: now, update: change } = latest.current;
      const r = el.getBoundingClientRect();
      const point = { x: e.clientX - r.left, y: e.clientY - r.top };
      // A trackpad pinch arrives as a wheel with ctrl held, and a mouse wheel
      // in lines (Firefox) or in a multiple of 100 or 120 pixels, one or more
      // notches (Chrome, Edge). Anything else is a two-finger scroll, which
      // pans: a fast swipe can send a whole number too, just rarely one of those.
      const pinch = e.ctrlKey;
      const notched = e.deltaMode !== 0 || (e.deltaX === 0 && e.deltaY !== 0 && (e.deltaY % 100 === 0 || e.deltaY % 120 === 0));
      wake();
      if (pinch || notched) {
        e.preventDefault();
        const factor = Math.exp(-e.deltaY * (pinch ? 0.01 : 0.002));
        change((v, st) => zoomAt(v, v.scale * factor, point, st));
      } else if (!isFit(now)) {
        e.preventDefault();
        change((v, st) => panBy(v, -e.deltaX, -e.deltaY, st));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [wake]);

  const pointIn = (e: { clientX: number; clientY: number }): Point => {
    const r = frameRef.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  const endPress = () => {
    endedDrag.current = press.current?.moved ?? false;
    press.current = null;
    setDragging(false);
  };

  const fit = isFit(view);
  const shown = ready(stage);
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div
        ref={frameRef}
        data-testid="zoom-frame"
        className={cn(
          "relative min-h-0 flex-1 overflow-hidden rounded-md bg-hairline/30 select-none",
          // Touch keeps the browser's own pinch and scroll at fit; zoomed in, a
          // finger drags the image instead.
          fit ? "cursor-zoom-in" : cn("touch-none", dragging ? "cursor-grabbing" : "cursor-grab"),
        )}
        onClick={(e) => {
          if (endedDrag.current) {
            endedDrag.current = false;
            return;
          }
          // The second click of a double-click: the first already zoomed.
          if (e.detail >= 2) return;
          wake();
          const at = pointIn(e);
          update((v, st) => toggleAt(v, at, st));
        }}
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          press.current = { id: e.pointerId, startX: e.clientX, startY: e.clientY, x: e.clientX, y: e.clientY, moved: false };
          endedDrag.current = false;
          if (!fit) e.currentTarget.setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          wake();
          const p = press.current;
          if (!p || p.id !== e.pointerId) return;
          if (!p.moved && Math.hypot(e.clientX - p.startX, e.clientY - p.startY) > CLICK_SLOP) {
            p.moved = true;
            if (!fit) setDragging(true);
          }
          const dx = e.clientX - p.x;
          const dy = e.clientY - p.y;
          p.x = e.clientX;
          p.y = e.clientY;
          if (!fit) update((v, st) => panBy(v, dx, dy, st));
        }}
        onPointerUp={endPress}
        onPointerCancel={endPress}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset */}
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          draggable={false}
          onLoad={measureImage}
          className={cn("absolute top-0 left-0 block max-w-none origin-top-left", !shown && "invisible")}
          style={
            shown
              ? {
                  width: stage.fitted.width,
                  height: stage.fitted.height,
                  transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
                }
              : undefined
          }
        />
        {!fit && shown && (
          <Minimap
            src={src}
            view={view}
            stage={stage}
            awake={awake || dragging}
            onCenter={(point) => {
              wake();
              update((v, st) => centerOn(v, point, st));
            }}
          />
        )}
      </div>
      <div role="group" aria-label="Zoom" className="flex items-center justify-center gap-1">
        <IconButton label="Zoom out" side="top" disabled={fit} onClick={() => zoomBy(1 / ZOOM_STEP)}>
          <Minus />
        </IconButton>
        <button
          type="button"
          title="Fit to the window (0)"
          aria-label={fit ? "Fit" : `${readout(view, stage)}, fit to the window`}
          disabled={fit}
          onClick={() => setZoomed(null)}
          className="min-w-12 rounded-md px-1.5 py-0.5 text-center tabular text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text disabled:hover:bg-transparent"
        >
          {readout(view, stage)}
        </button>
        <IconButton label="Zoom in" side="top" disabled={!shown || view.scale >= maxScale(stage)} onClick={() => zoomBy(ZOOM_STEP)}>
          <Plus />
        </IconButton>
      </div>
    </div>
  );
}

/**
 * The whole image, small, in the bottom-right corner, with a rectangle around
 * the part in view. Pressing it moves the view there and dragging carries the
 * view along; grabbing the rectangle keeps the point grabbed under the
 * pointer. Its presses stay its own, so the image under it doesn't pan or
 * zoom. Not shown on small screens, where it would cover what it maps.
 */
function Minimap({
  src,
  view,
  stage,
  awake,
  onCenter,
}: {
  src: string;
  view: View;
  stage: Stage;
  /** Shown fully; otherwise faded, letting presses through, until the pointer moves. */
  awake: boolean;
  /** Center the view on this point of the image, in the fitted image's pixels. */
  onCenter: (point: Point) => void;
}) {
  const { fitted } = stage;
  // Its longest side is MINIMAP_SIZE, so a tall image's map is tall and narrow
  // rather than as tall as the frame.
  const k = Math.min(MINIMAP_SIZE / fitted.width, MINIMAP_SIZE / fitted.height, 0.3);
  const seen = inView(view, stage);
  const grab = useRef<{ id: number; dx: number; dy: number } | null>(null);

  const at = (e: PointerEvent<HTMLDivElement>): Point => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: (e.clientX - r.left) / k, y: (e.clientY - r.top) / k };
  };

  return (
    <div
      data-testid="minimap"
      aria-hidden
      className={cn(
        "absolute right-2 bottom-2 hidden cursor-pointer touch-none overflow-hidden rounded border border-white/70 bg-surface shadow-md transition-opacity duration-300 sm:block",
        // Faded, it lets presses through to the image, so a tap on a tablet
        // (which may send no move first) zooms out rather than moving the
        // view. Any movement over the image wakes it again.
        awake ? "opacity-100" : "pointer-events-none opacity-0",
      )}
      style={{ width: fitted.width * k, height: fitted.height * k }}
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => {
        e.stopPropagation();
        if (e.button !== 0) return;
        const p = at(e);
        const inside = p.x >= seen.x && p.x <= seen.x + seen.width && p.y >= seen.y && p.y <= seen.y + seen.height;
        const dx = inside ? p.x - (seen.x + seen.width / 2) : 0;
        const dy = inside ? p.y - (seen.y + seen.height / 2) : 0;
        grab.current = { id: e.pointerId, dx, dy };
        e.currentTarget.setPointerCapture?.(e.pointerId);
        onCenter({ x: p.x - dx, y: p.y - dy });
      }}
      onPointerMove={(e) => {
        e.stopPropagation();
        const g = grab.current;
        if (!g || g.id !== e.pointerId) return;
        const p = at(e);
        onCenter({ x: p.x - g.dx, y: p.y - g.dy });
      }}
      onPointerUp={(e) => {
        e.stopPropagation();
        grab.current = null;
      }}
      onPointerCancel={() => {
        grab.current = null;
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset */}
      <img src={src} alt="" draggable={false} className="block size-full" />
      <div
        data-testid="minimap-view"
        className="pointer-events-none absolute border-2 border-accent bg-accent/15"
        style={{ left: seen.x * k, top: seen.y * k, width: seen.width * k, height: seen.height * k }}
      />
    </div>
  );
}
