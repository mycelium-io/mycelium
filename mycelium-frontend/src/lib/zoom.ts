// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Zooming and panning an image inside the box it's fitted to.
//
// A view is a scale relative to that fitted size (1 is fit) and the offset of
// the image's top-left corner in the box, in CSS pixels. The image is drawn
// with `translate(x, y) scale(scale)` from its top-left corner, so a point of
// the box stays put when zooming around it, and the image always covers the
// box: it can't be zoomed out past fit or panned off an edge.

export interface View {
  scale: number;
  x: number;
  y: number;
}

export interface Point {
  x: number;
  y: number;
}

/** The box the image is fitted to, which is the image's own size at fit. */
export interface Box {
  width: number;
  height: number;
}

export const FIT: View = { scale: 1, x: 0, y: 0 };

/** How far it zooms in, relative to fit (more when 100% is further). */
export const MAX_ZOOM = 8;

/** One press of + or −, or of the buttons. */
export const ZOOM_STEP = 1.25;

/** The scale at which the image is drawn at its own size: 100%. */
export function actualSize(box: Box, naturalWidth: number): number {
  return box.width > 0 && naturalWidth > 0 ? naturalWidth / box.width : 1;
}

export function maxScale(box: Box, naturalWidth: number): number {
  return Math.max(MAX_ZOOM, actualSize(box, naturalWidth));
}

export function isFit(view: View): boolean {
  return view.scale <= 1;
}

/** `view` moved back inside the box, so no edge of the box shows past the image. */
export function clampPan(view: View, box: Box): View {
  const minX = box.width - box.width * view.scale;
  const minY = box.height - box.height * view.scale;
  return {
    scale: view.scale,
    x: Math.min(0, Math.max(minX, view.x)),
    y: Math.min(0, Math.max(minY, view.y)),
  };
}

/** Zoom to `scale` (clamped between fit and `max`), keeping `point` of the box where it is. */
export function zoomAt(view: View, scale: number, point: Point, box: Box, max: number): View {
  const s = Math.min(max, Math.max(1, scale));
  if (s <= 1) return FIT;
  const k = s / view.scale;
  return clampPan({ scale: s, x: point.x - (point.x - view.x) * k, y: point.y - (point.y - view.y) * k }, box);
}

export function panBy(view: View, dx: number, dy: number, box: Box): View {
  if (isFit(view)) return view;
  return clampPan({ scale: view.scale, x: view.x + dx, y: view.y + dy }, box);
}

/** A double-click: back to fit when zoomed, else to 100% at `point` (2x when
 *  the image already fits at its own size). */
export function toggleAt(view: View, point: Point, box: Box, naturalWidth: number): View {
  if (!isFit(view)) return FIT;
  const actual = actualSize(box, naturalWidth);
  return zoomAt(view, actual > 1.01 ? actual : 2, point, box, maxScale(box, naturalWidth));
}

/** What the zoom readout says: "Fit", or the share of the image's own size. */
export function readout(view: View, box: Box, naturalWidth: number): string {
  if (isFit(view)) return "Fit";
  return `${Math.round((view.scale / actualSize(box, naturalWidth)) * 100)}%`;
}
