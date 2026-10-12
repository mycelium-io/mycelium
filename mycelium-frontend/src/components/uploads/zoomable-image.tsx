// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type PointerEvent, type Ref } from "react";
import { Minus, Plus } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import {
  centerOn,
  FIT,
  inView,
  isFit,
  maxScale,
  panBy,
  readout,
  toggleAt,
  zoomAt,
  ZOOM_STEP,
  type Box,
  type Point,
  type View,
} from "@/lib/zoom";
import { cn } from "@/lib/utils";

/** What the preview window asks of the image for its keys. */
export interface ZoomKeys {
  /** Act on a key, and say whether it was used (+, −, 0, and arrows while zoomed). */
  key: (key: string) => boolean;
}

/** An arrow key moves this share of the box. */
const PAN_STEP = 0.1;

/** A press that moves no further than this many pixels is a click, not a drag. */
const CLICK_SLOP = 4;

/** The minimap fades after the pointer has been still this long. */
const MINIMAP_IDLE_MS = 2000;

/** The minimap's width: this many pixels, or less on a narrow image. */
const MINIMAP_WIDTH = 160;

/**
 * An image fitted to the window that zooms and pans the way image viewers do.
 * A click zooms in to 100% at the point clicked, and a click while zoomed goes
 * back to fit (a double-click counts as one click). Dragging pans while zoomed
 * in, and so does a two-finger scroll. The wheel or a pinch zooms around the
 * pointer, and the window passes its keys on through `ref`. While zoomed in, a
 * minimap in the corner shows the part in view and moves it when dragged. The
 * readout under the image says how far in it is, with − and + beside it, and
 * goes back to fit when clicked.
 */
export function ZoomableImage({ src, alt, ref }: { src: string; alt: string; ref?: Ref<ZoomKeys> }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [view, setView] = useState<View>(FIT);
  const [box, setBox] = useState<Box>({ width: 0, height: 0 });
  const [natural, setNatural] = useState(0);
  const [dragging, setDragging] = useState(false);
  const press = useRef<{ id: number; startX: number; startY: number; x: number; y: number; moved: boolean } | null>(null);
  // The press that ended last was a drag, so the click that follows it isn't one.
  const endedDrag = useRef(false);

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
  const latest = useRef({ view, box, natural });
  useEffect(() => {
    latest.current = { view, box, natural };
  });

  const measure = () => {
    const img = imgRef.current;
    if (!img) return;
    setBox({ width: img.clientWidth, height: img.clientHeight });
    setNatural(img.naturalWidth);
  };

  // An image already loaded (from the cache) has fired its load before this.
  // A new window size changes the fitted box the view is measured in, so it
  // goes back to fit. A transform never changes the box, so zooming doesn't.
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    if (img.complete) measure();
    if (typeof ResizeObserver === "undefined") return;
    const seen = new ResizeObserver(() => {
      const { box: was } = latest.current;
      if (img.clientWidth === was.width && img.clientHeight === was.height) return;
      setBox({ width: img.clientWidth, height: img.clientHeight });
      setView(FIT);
    });
    seen.observe(img);
    return () => seen.disconnect();
  }, []);

  const center = (): Point => ({ x: box.width / 2, y: box.height / 2 });
  const zoomBy = (factor: number, point: Point = center()) =>
    setView((v) => zoomAt(v, v.scale * factor, point, box, maxScale(box, natural)));

  useImperativeHandle(ref, () => ({
    key(key: string) {
      wake();
      if (key === "+" || key === "=") {
        zoomBy(ZOOM_STEP);
      } else if (key === "-" || key === "_") {
        zoomBy(1 / ZOOM_STEP);
      } else if (key === "0") {
        setView(FIT);
      } else if (key.startsWith("Arrow") && !isFit(view)) {
        const dx = box.width * PAN_STEP;
        const dy = box.height * PAN_STEP;
        const [mx, my] = { ArrowLeft: [dx, 0], ArrowRight: [-dx, 0], ArrowUp: [0, dy], ArrowDown: [0, -dy] }[key] ?? [0, 0];
        setView((v) => panBy(v, mx, my, box));
      } else {
        return false;
      }
      return true;
    },
  }));

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const onWheel = (e: WheelEvent) => {
      const { view: now, box: b, natural: n } = latest.current;
      const r = frame.getBoundingClientRect();
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
        setView((v) => zoomAt(v, v.scale * factor, point, b, maxScale(b, n)));
      } else if (!isFit(now)) {
        e.preventDefault();
        setView((v) => panBy(v, -e.deltaX, -e.deltaY, b));
      }
    };
    frame.addEventListener("wheel", onWheel, { passive: false });
    return () => frame.removeEventListener("wheel", onWheel);
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
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        ref={frameRef}
        data-testid="zoom-frame"
        className={cn(
          "relative max-w-full overflow-hidden rounded-md select-none",
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
          setView((v) => toggleAt(v, pointIn(e), box, natural));
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
          if (!fit) setView((v) => panBy(v, dx, dy, box));
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
          onLoad={measure}
          className="block max-h-[70vh] max-w-full origin-top-left object-contain"
          style={fit ? undefined : { transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        />
        {!fit && box.width > 0 && (
          <Minimap
            src={src}
            view={view}
            box={box}
            awake={awake || dragging}
            onCenter={(point) => {
              wake();
              setView((v) => centerOn(v, point, box));
            }}
          />
        )}
      </div>
      <div role="group" aria-label="Zoom" className="flex items-center gap-1">
        <IconButton label="Zoom out" side="top" disabled={fit} onClick={() => zoomBy(1 / ZOOM_STEP)}>
          <Minus />
        </IconButton>
        <button
          type="button"
          title="Fit to the window (0)"
          aria-label={fit ? "Fit" : `${readout(view, box, natural)}, fit to the window`}
          disabled={fit}
          onClick={() => setView(FIT)}
          className="min-w-12 rounded-md px-1.5 py-0.5 text-center tabular text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text disabled:hover:bg-transparent"
        >
          {readout(view, box, natural)}
        </button>
        <IconButton label="Zoom in" side="top" disabled={view.scale >= maxScale(box, natural)} onClick={() => zoomBy(ZOOM_STEP)}>
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
  box,
  awake,
  onCenter,
}: {
  src: string;
  view: View;
  box: Box;
  /** Shown fully; otherwise faded until the pointer moves or rests on it. */
  awake: boolean;
  /** Center the view on this point of the image, in the fitted box's pixels. */
  onCenter: (point: Point) => void;
}) {
  const width = Math.min(MINIMAP_WIDTH, box.width * 0.3);
  const k = width / box.width;
  const seen = inView(view, box);
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
        "absolute right-2 bottom-2 hidden cursor-pointer touch-none overflow-hidden rounded border border-white/70 bg-surface shadow-md transition-opacity duration-300 hover:opacity-100 sm:block",
        awake ? "opacity-100" : "opacity-0",
      )}
      style={{ width, height: box.height * k }}
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
