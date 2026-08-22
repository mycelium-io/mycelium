// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { SVGProps } from "react";

/**
 * Remix Icon `send-plane-fill`, vendored as a single path.
 *
 * Upstream: Remix-Design/RemixIcon (Apache-2.0), icons/Business/send-plane-fill.svg.
 * Vendored rather than taking an icon-set dependency: one 16px glyph doesn't
 * justify pulling in `react-icons`, and the upstream license already matches
 * this repo's. Refresh by re-copying the path from an updated checkout.
 *
 * The plane flies up-and-right, which is the reason it's this glyph and not a
 * flat-right one: the composer sits below the transcript, so a message travels
 * *up* into the room as much as it travels *out* to its members.
 *
 * The viewBox is shifted off 0 0 deliberately. Upstream centers the path by its
 * bounding box, but a solid triangle reads from its ink, and this one's area
 * centroid sits 2.1 right and 1.8 up of the box center — enough to look visibly
 * shoved into the corner of a round button. The offset walks 70% of the way to
 * the centroid: full correction swings the other way and crowds the nose
 * against the right edge. Nothing is clipped at this offset.
 */
export function SendPlaneIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="1.476 -1.238 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M1.94607 9.31543C1.42353 9.14125 1.4194 8.86022 1.95682 8.68108L21.043 2.31901C21.5715 2.14285 21.8746 2.43866 21.7265 2.95694L16.2733 22.0432C16.1223 22.5716 15.8177 22.59 15.5944 22.0876L11.9999 14L17.9999 6.00005L9.99992 12L1.94607 9.31543Z" />
    </svg>
  );
}
