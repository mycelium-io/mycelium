// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The security headers the app's pages go out with, set in `next.config.ts`.
// Kept here, apart from the config, so a test can check them.

/** Every path except `/api`. An `/api` response keeps the hub's own headers,
 *  and an upload is served under a stricter policy that this mustn't replace. */
export const PAGE_ROUTES = "/((?!api/).*)";

/** Who may show the app's pages in a frame: the app itself, a page served on
 *  this machine, and the published slides. The talk and workshop decks
 *  (`mycelium-io/slides`) frame the live app on this machine, from a local
 *  server or from the published site. */
export const FRAME_ANCESTORS = [
  "'self'",
  "http://127.0.0.1:*",
  "http://localhost:*",
  "https://mycelium-io.github.io",
];

/** The policy every page carries. `frame-ancestors` stops any other site
 *  showing the app in a frame, where it could lay its own buttons over the
 *  app's and have the person click through to them. `object-src` and
 *  `base-uri` shut out a plugin and a `<base>` tag, which markup slipped into a
 *  page could otherwise use. It names no script source, so the app's pages
 *  need no nonce or hash. */
export const PAGE_CSP = `frame-ancestors ${FRAME_ANCESTORS.join(" ")}; object-src 'none'; base-uri 'none'`;

// No `X-Frame-Options`: it can't name the frames allowed above, and every
// browser the app runs in reads `frame-ancestors` and ignores it.
export const PAGE_SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: PAGE_CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
];
