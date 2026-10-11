// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { Minus, Plus } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import {
  FIT,
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

/**
 * An image fitted to the window that can be zoomed and moved around: wheel or
 * pinch around the pointer, double-click between fit and 100%, drag or
 * two-finger scroll to pan, and the keys the window passes on through `ref`.
 * The readout under it says how far in it is, with − and + beside it, and goes
 * back to fit when clicked.
 */
export function ZoomableImage({ src, alt, ref }: { src: string; alt: string; ref?: Ref<ZoomKeys> }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [view, setView] = useState<View>(FIT);
  const [box, setBox] = useState<Box>({ width: 0, height: 0 });
  const [natural, setNatural] = useState(0);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ id: number; x: number; y: number } | null>(null);
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
  }, []);

  const pointIn = (e: { clientX: number; clientY: number }): Point => {
    const r = frameRef.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  const fit = isFit(view);
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        ref={frameRef}
        data-testid="zoom-frame"
        className={cn(
          "max-w-full overflow-hidden rounded-md select-none",
          // Touch keeps the browser's own pinch and scroll at fit; zoomed in, a
          // finger drags the image instead.
          fit ? "cursor-zoom-in" : cn("touch-none", dragging ? "cursor-grabbing" : "cursor-grab"),
        )}
        onDoubleClick={(e) => setView((v) => toggleAt(v, pointIn(e), box, natural))}
        onPointerDown={(e) => {
          if (fit || e.button !== 0) return;
          drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
          e.currentTarget.setPointerCapture?.(e.pointerId);
          setDragging(true);
        }}
        onPointerMove={(e) => {
          const from = drag.current;
          if (!from || from.id !== e.pointerId) return;
          drag.current = { id: from.id, x: e.clientX, y: e.clientY };
          setView((v) => panBy(v, e.clientX - from.x, e.clientY - from.y, box));
        }}
        onPointerUp={() => {
          drag.current = null;
          setDragging(false);
        }}
        onPointerCancel={() => {
          drag.current = null;
          setDragging(false);
        }}
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
