// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The browser session: OIDC tokens sealed in an httpOnly, AES-256-GCM cookie so
// they never reach the browser bundle. SERVER-SIDE only (route handlers + the
// proxy). The proxy calls `bearer()` to inject the access token; everything else
// reads/writes the cookie through here.

import { createHash } from "node:crypto";
import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";
import { oidcConfig } from "./auth-config";
import { endpoints, refreshTokens, claimsOf, handleFromClaims } from "./oidc";

export const SESSION_COOKIE = "myc_session";
export const TX_COOKIE = "myc_oidc_tx";
const SESSION_TTL_S = 60 * 60 * 12;
/** Refresh a little before expiry so an in-flight call never rides a dead token. */
const REFRESH_SKEW_S = 30;

export interface Session {
  access_token: string;
  refresh_token?: string;
  /** Access-token expiry, epoch seconds. */
  expires_at: number;
  handle: string;
}

function key(secret: string): Uint8Array {
  return new Uint8Array(createHash("sha256").update(secret).digest());
}

// Secure by default; self-hosted deployments with no TLS in front (the
// appliance path — see docs/guides/keycloak-oidc.md) opt out explicitly. Tying
// this to NODE_ENV instead would break every non-TLS deployment, since the
// built Docker image always runs with NODE_ENV=production regardless of
// whether the operator terminates TLS.
const secure = process.env.MYCELIUM_COOKIE_SECURE !== "false";
const cookieOpts = { httpOnly: true, sameSite: "lax" as const, secure, path: "/" };

export async function seal(payload: Record<string, unknown>, secret: string, ttlSec: number): Promise<string> {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(`${ttlSec}s`)
    .encrypt(key(secret));
}

export async function unseal<T = Record<string, unknown>>(token: string, secret: string): Promise<T | null> {
  try {
    const { payload } = await jwtDecrypt(token, key(secret));
    return payload as T;
  } catch {
    return null;
  }
}

export async function getSession(): Promise<Session | null> {
  const cfg = oidcConfig();
  if (!cfg) return null;
  const jar = await cookies();
  const raw = jar.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  return unseal<Session>(raw, cfg.sessionSecret);
}

export async function writeSession(s: Session): Promise<void> {
  const cfg = oidcConfig();
  if (!cfg) return;
  const sealed = await seal(s as unknown as Record<string, unknown>, cfg.sessionSecret, SESSION_TTL_S);
  const jar = await cookies();
  jar.set(SESSION_COOKIE, sealed, { ...cookieOpts, maxAge: SESSION_TTL_S });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, "", { ...cookieOpts, maxAge: 0 });
}

/**
 * Upstream request headers for an SSE proxy leg (events / notifications / room
 * stream). These routes don't go through the catch-all proxy, so they need the
 * bearer attached here too — otherwise a gated backend 401s the stream and the
 * UI silently stops updating. Adds nothing when there's no session.
 */
export async function upstreamSseHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
  };
  const token = await bearer();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/**
 * The bearer token to inject into a proxied `/api/*` call, refreshing it when
 * it's within the skew window. Returns null when there is no session — gate off
 * or signed out — so the proxy simply forwards no Authorization header, exactly
 * as before this existed.
 */
export async function bearer(): Promise<string | null> {
  const cfg = oidcConfig();
  if (!cfg) return null;
  const s = await getSession();
  if (!s) return null;

  const now = Math.floor(Date.now() / 1000);
  if (s.expires_at - REFRESH_SKEW_S > now) return s.access_token;
  // Expired (or nearly). Without a refresh token, send it and let the backend
  // 401 — the client's session poll then re-engages the gate.
  if (!s.refresh_token) return s.access_token;

  try {
    const ep = await endpoints(cfg);
    const t = await refreshTokens(cfg, ep, s.refresh_token);
    const next: Session = {
      access_token: t.access_token,
      refresh_token: t.refresh_token ?? s.refresh_token,
      expires_at: now + (t.expires_in ?? 300),
      handle: handleFromClaims(claimsOf(t.access_token), cfg.handleClaim) || s.handle,
    };
    await writeSession(next);
    return next.access_token;
  } catch {
    // Refresh failed (revoked / IdP down): drop the session and forward nothing.
    await clearSession();
    return null;
  }
}
