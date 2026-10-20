// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What the UI server asks of a request before it does anything with it.
 * SERVER-SIDE only (`proxy.ts` and the `/api` route handlers).
 *
 * The server forwards to the hub with the person's sign-in when it holds one,
 * so a request that isn't from this app's own pages must not get through:
 *
 * - **Host** must be a name this server serves: loopback, an IP address, or
 *   the configured public name (`MYCELIUM_UI_HOST`, from `ui.public_host`).
 *   A page that rebinds its own name to this machine still sends that name,
 *   which is why a bare IP address is safe to allow (and why Docker installs
 *   opened by LAN address keep working).
 * - **Origin**, when the browser sends one, must be this server's own.
 * - **A body** must be JSON, except an upload (`multipart/form-data`) and the
 *   few routes that take raw bytes (`RAW_BODY_PATHS`).
 * - **Proof** it comes from the app's pages: in the desktop app, the token for
 *   this launch (`MYCELIUM_UI_TOKEN`), which the app hands its window in the
 *   URL fragment and the page sends as a header (or a query parameter, where a
 *   browser can't set one: `EventSource`, `<img>`). Never served by this server,
 *   so a program on the machine can't fetch it. Where no token is set (Docker,
 *   a server like the hosted one, `pnpm dev`) the proof is the hub's own
 *   sign-in: the session cookie on that site, and with the hub's gate off there
 *   is nothing to take, since the hub answers callers directly.
 */

import { timingSafeEqual } from "node:crypto";

export const TOKEN_HEADER = "x-mycelium-ui";
export const TOKEN_PARAM = "mycelium-ui";

/** `/api` routes reached by a top-level navigation, which can carry nothing. */
const NAVIGATION_PATHS = ["/api/auth/login", "/api/auth/callback"];
/** Routes whose body is raw bytes the hub reads as such: an open mic's audio. */
const RAW_BODY_PATHS = [/^\/api\/voice\/sessions\/[^/]+$/];

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** This launch's token, when the desktop app started this server. */
export function launchToken(): string | null {
  const token = process.env.MYCELIUM_UI_TOKEN?.trim();
  return token ? token : null;
}

/** The public name this server is also reached by, when it has one. */
export function publicHost(): string | null {
  const host = process.env.MYCELIUM_UI_HOST?.trim().toLowerCase();
  return host ? host.replace(/:\d+$/, "") : null;
}

/** The host part of a `Host` header, without its port. */
function hostname(host: string): string {
  const h = host.trim().toLowerCase();
  if (h.startsWith("[")) return h.slice(0, h.indexOf("]") + 1);
  return h.replace(/:\d+$/, "");
}

const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

/** Whether `host` (a `Host` header) is one this server answers to. */
export function hostAllowed(host: string | null, configured: string | null = publicHost()): boolean {
  if (!host) return false;
  const name = hostname(host);
  if (name === "localhost" || IPV4.test(name)) return true;
  if (name.startsWith("[") && name.endsWith("]") && name.includes(":")) return true;
  return configured !== null && name === configured;
}

function tokenMatches(given: string | null, expected: string): boolean {
  if (!given) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** Whether the request carries this launch's token. */
export function carriesToken(req: Request, expected: string | null = launchToken()): boolean {
  if (!expected) return false;
  const header = req.headers.get(TOKEN_HEADER);
  const param = new URL(req.url).searchParams.get(TOKEN_PARAM);
  return tokenMatches(header, expected) || tokenMatches(param, expected);
}

function refuse(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

/**
 * Why an `/api` request is refused, as the response to send, or `null` when
 * it may go on. `token` is this launch's token, `null` where none is set.
 */
export function guardApi(req: Request, token: string | null = launchToken()): Response | null {
  const url = new URL(req.url);
  const host = req.headers.get("host");
  if (!hostAllowed(host)) return refuse(421, "This server doesn't answer to that name.");

  const origin = req.headers.get("origin");
  if (origin && origin !== "null") {
    let own = false;
    try {
      own = new URL(origin).host.toLowerCase() === (host ?? "").toLowerCase();
    } catch {
      own = false;
    }
    if (!own) return refuse(403, "Requests from another site aren't accepted.");
  } else if (origin === "null") {
    return refuse(403, "Requests from another site aren't accepted.");
  }
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") {
    if (!NAVIGATION_PATHS.includes(url.pathname)) {
      return refuse(403, "Requests from another site aren't accepted.");
    }
  }

  if (UNSAFE.has(req.method)) {
    const type = (req.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
    const length = req.headers.get("content-length");
    const noBody = type === "" && (length === null || length === "0");
    const raw = RAW_BODY_PATHS.some((p) => p.test(url.pathname)) && type === "application/octet-stream";
    const ok = noBody || raw || type === "application/json" || type === "multipart/form-data";
    if (!ok) return refuse(415, "A request body must be JSON.");
  }

  if (token && !NAVIGATION_PATHS.includes(url.pathname) && !carriesToken(req, token)) {
    return refuse(401, "This request didn't come from Mycelium's own window.");
  }
  return null;
}
