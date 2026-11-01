// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Zooming and panning an image inside a frame, the way image viewers do.
//
// The frame is the viewport: its size comes from the window, never from the
// image. The image starts fitted inside it, whole and centered, and never
// larger than its own size. A view is a scale relative to that fitted size (1
// is fit) and where the image's top-left corner sits in the frame, in CSS
// pixels. The image is drawn with `translate(x, y) scale(scale)` from its
// top-left corner, so a point of the frame stays put when zooming around it.
// Zoomed in, the image grows past the frame on both axes and pans until an
// edge meets the frame's edge; a side still smaller than the frame stays
// centered on it.

export interface View {
  scale: number;
  x: number;
  y: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

/** What the view is measured against: the frame, the image's own size, and
 *  the size it's drawn at to fit (see `stageOf`). */
export interface Stage {
  frame: Size;
  natural: Size;
  fitted: Size;
}

/** How far it zooms in, relative to fit (more when 100% is further). */
export const MAX_ZOOM = 8;

/** One press of + or −, or of the buttons. */
export const ZOOM_STEP = 1.25;

/** The stage for an image of `natural` size in a frame of `frame` size: the
 *  image contained in the frame, never enlarged past its own size. */
export function stageOf(frame: Size, natural: Size): Stage {
  if (frame.width <= 0 || frame.height <= 0 || natural.width <= 0 || natural.height <= 0) {
    return { frame, natural, fitted: { width: 0, height: 0 } };
  }
  const k = Math.min(1, frame.width / natural.width, frame.height / natural.height);
  return { frame, natural, fitted: { width: natural.width * k, height: natural.height * k } };
}

export function ready(st: Stage): boolean {
  return st.fitted.width > 0 && st.fitted.height > 0;
}

/** The image whole and centered in the frame. */
export function fitView(st: Stage): View {
  return {
    scale: 1,
    x: (st.frame.width - st.fitted.width) / 2,
    y: (st.frame.height - st.fitted.height) / 2,
  };
}

/** The scale at which the image is drawn at its own size: 100%. */
export function actualSize(st: Stage): number {
  return ready(st) ? st.natural.width / st.fitted.width : 1;
}

export function maxScale(st: Stage): number {
  return Math.max(MAX_ZOOM, actualSize(st));
}

export function isFit(view: View): boolean {
  return view.scale <= 1;
}

/** One axis: an image wider than the frame stops at its edges; a narrower one is centered. */
function clampAxis(at: number, image: number, frame: number): number {
  if (image <= frame) return (frame - image) / 2;
  return Math.min(0, Math.max(frame - image, at));
}

/** `view` moved back so no empty space shows past the image's edges. */
export function clampPan(view: View, st: Stage): View {
  return {
    scale: view.scale,
    x: clampAxis(view.x, st.fitted.width * view.scale, st.frame.width),
    y: clampAxis(view.y, st.fitted.height * view.scale, st.frame.height),
  };
}

/** Zoom to `scale` (clamped between fit and the most it zooms), keeping
 *  `point` of the frame over the same spot of the image. */
export function zoomAt(view: View, scale: number, point: Point, st: Stage): View {
  const s = Math.min(maxScale(st), Math.max(1, scale));
  if (s <= 1) return fitView(st);
  const k = s / view.scale;
  return clampPan({ scale: s, x: point.x - (point.x - view.x) * k, y: point.y - (point.y - view.y) * k }, st);
}

export function panBy(view: View, dx: number, dy: number, st: Stage): View {
  if (isFit(view)) return view;
  return clampPan({ scale: view.scale, x: view.x + dx, y: view.y + dy }, st);
}

/** A click: back to fit when zoomed, else to 100% at `point` (2x when the
 *  image already fits at its own size). */
export function toggleAt(view: View, point: Point, st: Stage): View {
  if (!isFit(view)) return fitView(st);
  const actual = actualSize(st);
  return zoomAt(view, actual > 1.01 ? actual : 2, point, st);
}

/** The part of the image in view, in the fitted image's pixels. */
export function inView(view: View, st: Stage): { x: number; y: number; width: number; height: number } {
  const w = st.fitted.width * view.scale;
  const h = st.fitted.height * view.scale;
  return {
    x: Math.max(0, -view.x) / view.scale,
    y: Math.max(0, -view.y) / view.scale,
    width: Math.min(st.frame.width, w) / view.scale,
    height: Math.min(st.frame.height, h) / view.scale,
  };
}

/** `view` moved so the image's `point` (in the fitted image's pixels) is in
 *  the middle of the frame, as far as the edges allow. */
export function centerOn(view: View, point: Point, st: Stage): View {
  if (isFit(view)) return view;
  return clampPan(
    { scale: view.scale, x: st.frame.width / 2 - point.x * view.scale, y: st.frame.height / 2 - point.y * view.scale },
    st,
  );
}

/** What the zoom readout says: "Fit", or the share of the image's own size. */
export function readout(view: View, st: Stage): string {
  if (isFit(view)) return "Fit";
  return `${Math.round((view.scale / actualSize(st)) * 100)}%`;
}
