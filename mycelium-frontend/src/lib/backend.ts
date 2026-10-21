// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { MEDIA_PARAM, TOKEN_PARAM } from "./ui-guard";

/**
 * Resolve the internal backend URL: SERVER-SIDE, at REQUEST time.
 *
 * This MUST be evaluated per-request, never baked into the build: one image
 * runs in dev, Docker, and cloud against different backends. See next.config.ts
 * for the request proxy. Precedence:
 *
 *   1. MYCELIUM_INTERNAL_API_URL (compose / runtime env)
 *   2. server.api_url from ~/.mycelium/config.toml (matches the CLI)
 *   3. http://localhost:8000 (mycelium install default)
 *
 * Only import this from server code (route handlers); it reads the filesystem.
 */
export function getBackendUrl(): string {
  if (process.env.MYCELIUM_INTERNAL_API_URL) return process.env.MYCELIUM_INTERNAL_API_URL;
  try {
    const text = readFileSync(join(homedir(), ".mycelium", "config.toml"), "utf8");
    const m =
      text.match(/\[server\][\s\S]*?\n\s*api_url\s*=\s*"([^"]+)"/) ??
      text.match(/^\s*api_url\s*=\s*"([^"]+)"/m);
    if (m) return m[1];
  } catch {
    /* no config; fall through */
  }
  return "http://localhost:8000";
}

/**
 * Where a proxied request goes: the hub, with the launch's token and any media
 * signature taken off the query, so the hub never sees them and its log never
 * holds them (`lib/ui-guard.ts`). The backend serves health at the root
 * (`/health`), while everything else it exposes is under `/api`, so the
 * proxied `/api/health` maps onto the root for the health and fabric views.
 */
export function upstreamUrl(backend: string, requestUrl: string): string {
  const url = new URL(requestUrl);
  url.searchParams.delete(TOKEN_PARAM);
  url.searchParams.delete(MEDIA_PARAM);
  const path = url.pathname === "/api/health" ? "/health" : url.pathname;
  return `${backend}${path}${url.search}`;
}

/** Headers that belong to one hop and must not be forwarded across another. */
const HOP_BY_HOP = ["host", "connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"];
/**
 * What the browser said about the page, which this server has already checked
 * (`lib/ui-guard.ts`). The request on to the hub is this server's own call,
 * not the browser's: forwarded, the page's origin reaches a hub that serves
 * its own UI as a request from another site, and is refused. The hub never
 * reads cookies (the sign-in goes as a bearer), and on 127.0.0.1 the browser
 * sends every local app's, so none go on to a hub on another machine.
 */
const BROWSER_CONTEXT = ["origin", "referer", "cookie"];
const BROWSER_CONTEXT_PREFIX = "sec-fetch-";

/** The page's request headers as this server sends them on to the hub. */
export function upstreamHeaders(req: Request): Headers {
  const headers = new Headers(req.headers);
  for (const h of [...HOP_BY_HOP, ...BROWSER_CONTEXT]) headers.delete(h);
  for (const name of [...headers.keys()]) {
    if (name.startsWith(BROWSER_CONTEXT_PREFIX)) headers.delete(name);
  }
  return headers;
}
