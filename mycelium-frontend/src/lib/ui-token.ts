// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The desktop app's token for this launch, as the page holds it.
 *
 * The app opens its window on a URL whose fragment carries the token
 * (`#mycelium-ui=…`); a fragment never reaches a server or a log. The page takes
 * it out of the address on load and keeps it for the tab (sessionStorage, which
 * dies with the window), and every request to the UI server's `/api` carries it:
 * `fetch` as a header (installed once, so no call site has to remember), and
 * what can't set a header (`EventSource`, `<img>`, an upload's XHR) by
 * `withUiToken` or `uiTokenHeaders`. Outside the desktop app there's no token
 * and all of this does nothing (`lib/ui-guard.ts` says what applies there).
 */

import { hmac } from "@noble/hashes/hmac";
import { sha256 } from "@noble/hashes/sha2";
import { bytesToHex } from "@noble/hashes/utils";

export const TOKEN_HEADER = "x-mycelium-ui";
export const TOKEN_PARAM = "mycelium-ui";
const STORE_KEY = "mycelium-ui-token";

let token: string | null | undefined;

function read(): string | null {
  if (typeof window === "undefined") return null;
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const given = hash.get(TOKEN_PARAM);
  if (given) {
    try {
      window.sessionStorage.setItem(STORE_KEY, given);
    } catch {
      // Kept in memory only, then: a reload asks the app to open the window again.
    }
    hash.delete(TOKEN_PARAM);
    const rest = hash.toString();
    const clean = window.location.pathname + window.location.search + (rest ? `#${rest}` : "");
    window.history.replaceState(window.history.state, "", clean);
    return given;
  }
  try {
    return window.sessionStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

/** This launch's token, or `null` outside the desktop app. */
export function uiToken(): string | null {
  if (token === undefined) token = read();
  return token;
}

function isOwnApi(url: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    const u = new URL(url, window.location.href);
    return u.origin === window.location.origin && /^\/api\//.test(u.pathname);
  } catch {
    return false;
  }
}

/** `url` with the token as a query parameter, for the one request that can't
 *  send a header and never shows its URL to anyone: the `EventSource`. Media
 *  and downloads use `signedMediaUrl`. */
export function withUiToken(url: string): string;
export function withUiToken(url: string | null | undefined): string | null | undefined;
export function withUiToken(url: string | null | undefined): string | null | undefined {
  const t = uiToken();
  if (!url || !t || !isOwnApi(url)) return url;
  const u = new URL(url, window.location.href);
  u.searchParams.set(TOKEN_PARAM, t);
  return url.startsWith("http") ? u.toString() : u.pathname + u.search + u.hash;
}

export const MEDIA_PARAM = "mycelium-media";
/** How long a media signature lasts: to the end of the next window of this many seconds. */
const MEDIA_WINDOW_S = 600;

/**
 * `url` signed for an `<img>`, `<video>`, a PDF or a download: a signature of
 * its path and an expiry, keyed with the launch's token, so the token itself
 * never sits in a link someone could copy, and a signature is good for that one
 * file for 10 to 20 minutes. Stable within a window, so a re-render doesn't
 * reload the image. The server checks it (`lib/ui-guard.ts`, `mediaSignatureOk`).
 */
export function signedMediaUrl(url: string): string;
export function signedMediaUrl(url: string | null | undefined): string | null | undefined;
export function signedMediaUrl(url: string | null | undefined): string | null | undefined {
  const t = uiToken();
  if (!url || !t || !isOwnApi(url)) return url;
  const u = new URL(url, window.location.href);
  const exp = (Math.floor(Date.now() / 1000 / MEDIA_WINDOW_S) + 2) * MEDIA_WINDOW_S;
  u.searchParams.set(MEDIA_PARAM, `${exp}.${mediaSignature(t, u.pathname, exp)}`);
  return url.startsWith("http") ? u.toString() : u.pathname + u.search + u.hash;
}

/** HMAC-SHA256 of `path` and `exp`, keyed with the launch's token, in hex. */
export function mediaSignature(token: string, path: string, exp: number): string {
  const enc = new TextEncoder();
  return bytesToHex(hmac(sha256, enc.encode(token), enc.encode(`${path}\n${exp}`)));
}

/** The header to set on a request made some other way than `fetch`. */
export function uiTokenHeaders(): Record<string, string> {
  const t = uiToken();
  return t ? { [TOKEN_HEADER]: t } : {};
}

let installed = false;

/** Make every `fetch` to this server's `/api` carry the token. Once per page. */
export function installUiToken(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const t = uiToken();
  if (!t) return;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!isOwnApi(url)) return original(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set(TOKEN_HEADER, t);
    return original(input, { ...init, headers });
  };
}
