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

import { createHmac, timingSafeEqual } from "node:crypto";

export const TOKEN_HEADER = "x-mycelium-ui";
export const TOKEN_PARAM = "mycelium-ui";
export const MEDIA_PARAM = "mycelium-media";
/** The longest a media signature may still have to run when it's checked. */
const MEDIA_MAX_S = 30 * 60;

/**
 * `/api` routes reached by a top-level navigation, which can carry nothing:
 * the identity provider's redirect back, and a sign-in started as a `GET`.
 * A sign-in that starts as a `POST` from the page (#1412) carries the token
 * like any request; once no `GET` is left on that route, drop it here.
 */
const NAVIGATIONS: { path: string; methods: string[] }[] = [
  { path: "/api/auth/callback", methods: ["GET"] },
  { path: "/api/auth/login", methods: ["GET"] },
];

function isNavigation(req: Request, path: string): boolean {
  return NAVIGATIONS.some((n) => n.path === path && n.methods.includes(req.method));
}
/** Routes whose body is raw bytes the hub reads as such: an open mic's audio. */
const RAW_BODY_PATHS = [/^\/api\/voice\/sessions\/[^/]+$/];

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** This launch's token, when the desktop app started this server. */
export function launchToken(): string | null {
  const token = process.env.MYCELIUM_UI_TOKEN?.trim();
  return token ? token : null;
}

/** Whether the desktop app started this server, so a token was promised
 *  (`instrumentation.ts`), whether or not one arrived. */
export function tokenPromised(): boolean {
  return process.env.MYCELIUM_UI_TOKEN_STDIN === "1" || launchToken() !== null;
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

/** Whether the request carries this launch's token, or (for reading one file)
 *  a signature made with it for that file's path (`mediaSignatureOk`). */
export function carriesToken(req: Request, expected: string | null = launchToken()): boolean {
  if (!expected) return false;
  const url = new URL(req.url);
  const header = req.headers.get(TOKEN_HEADER);
  const param = url.searchParams.get(TOKEN_PARAM);
  if (tokenMatches(header, expected) || tokenMatches(param, expected)) return true;
  const media = url.searchParams.get(MEDIA_PARAM);
  return (req.method === "GET" || req.method === "HEAD") && mediaSignatureOk(media, url.pathname, expected);
}

/**
 * A media signature (`<exp>.<hex>`, `lib/ui-token.ts`'s `signedMediaUrl`): an
 * HMAC of the path and expiry keyed with the launch's token. Good for that one
 * path, until its expiry, which can't be more than `MEDIA_MAX_S` away.
 */
export function mediaSignatureOk(
  given: string | null,
  path: string,
  token: string,
  now: number = Math.floor(Date.now() / 1000),
): boolean {
  const [expRaw, sig] = (given ?? "").split(".", 2);
  const exp = Number(expRaw);
  if (!sig || !Number.isInteger(exp) || exp <= now || exp > now + MEDIA_MAX_S) return false;
  const expected = createHmac("sha256", token).update(`${path}\n${exp}`).digest("hex");
  return tokenMatches(sig, expected);
}

function refuse(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

/**
 * Why an `/api` request is refused, as the response to send, or `null` when
 * it may go on. `token` is this launch's token, `null` where none is set.
 */
export function guardApi(
  req: Request,
  token: string | null = launchToken(),
  promised: boolean = tokenPromised(),
): Response | null {
  const url = new URL(req.url);
  // The desktop app promised a token and none arrived: refuse everything,
  // never fall back to treating this as a server with no token.
  if (promised && !token) return refuse(503, "Mycelium's window token didn't arrive; restart Mycelium.");
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
    if (!isNavigation(req, url.pathname)) {
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

  if (token && !isNavigation(req, url.pathname) && !carriesToken(req, token)) {
    return refuse(401, "This request didn't come from Mycelium's own window.");
  }
  return null;
}
