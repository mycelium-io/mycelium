// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The security headers the app's pages go out with, set in `next.config.ts`.
// Kept here, apart from the config, so a test can check them.

/** Every path except `/api`. An `/api` response keeps the hub's own headers,
 *  and an upload is served under a stricter policy that this mustn't replace. */
export const PAGE_ROUTES = "/((?!api/).*)";

/** The policy every page carries. `frame-ancestors 'none'` stops another site
 *  showing the app in a frame, where it could lay its own buttons over the
 *  app's and have the person click through to them. `object-src` and
 *  `base-uri` shut out a plugin and a `<base>` tag, which markup slipped into a
 *  page could otherwise use. It names no script source, so the app's pages
 *  need no nonce or hash. */
export const PAGE_CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'none'";

export const PAGE_SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: PAGE_CSP },
  // What a browser that doesn't read `frame-ancestors` goes by.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
];
