// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Browser-tier OIDC configuration — SERVER-SIDE only (route handlers).
 *
 * Off by default, exactly like the backend gate: with no `MYCELIUM_OIDC_ISSUER`
 * and no `AUTH_SESSION_SECRET`, `oidcConfig()` returns null and the whole login
 * path stays inert (the localStorage handle-picker tier is unchanged). The UI
 * only engages OIDC when the backend advertises the gate is on *and* this is
 * configured.
 *
 * The issuer split mirrors the backend's issuer/jwks_url decoupling: the browser
 * reaches Keycloak at the public `issuer` (e.g. http://localhost:8080/realms/…),
 * but the Next.js server — in a container — cannot use that `localhost`, so it
 * makes discovery + token-exchange calls against `internalIssuer` (e.g.
 * http://keycloak:8080/realms/…). For `pnpm dev` on the host the two coincide.
 *
 * The desktop app's UI server sets none of that: it finds the hub's issuer
 * itself and keeps the sign-in in memory (`resolveOidcConfig`, `heldInMemory`).
 */

import { randomBytes } from "node:crypto";
import { getBackendUrl } from "./backend";

export interface OidcConfig {
  /** Public issuer the browser is redirected to and that stamps the token `iss`. */
  issuer: string;
  /** Base the Next.js server uses for discovery + token calls. Defaults to `issuer`. */
  internalIssuer: string;
  clientId: string;
  audience?: string;
  scopes: string;
  handleClaim: string;
  /** Secret used to seal the httpOnly session cookie (AES-256-GCM via a SHA-256 key). */
  sessionSecret: string;
}

function trimSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

export function oidcConfig(): OidcConfig | null {
  const issuer = process.env.MYCELIUM_OIDC_ISSUER?.trim();
  const sessionSecret = process.env.AUTH_SESSION_SECRET?.trim();
  // Both issuer and session secret are required to engage OIDC.
  if (!issuer || !sessionSecret) return null;
  const internal = process.env.MYCELIUM_OIDC_INTERNAL_ISSUER?.trim();
  return {
    issuer: trimSlash(issuer),
    internalIssuer: trimSlash(internal || issuer),
    clientId: process.env.MYCELIUM_OIDC_CLIENT_ID?.trim() || "mycelium-web",
    audience: process.env.MYCELIUM_OIDC_AUDIENCE?.trim() || undefined,
    scopes: process.env.MYCELIUM_OIDC_SCOPES?.trim() || "openid profile email",
    handleClaim: process.env.MYCELIUM_OIDC_HANDLE_CLAIM?.trim() || "preferred_username",
    sessionSecret,
  };
}

export function oidcConfigured(): boolean {
  return oidcConfig() != null;
}

/**
 * Whether this UI server keeps one person's sign-in in its own memory, never
 * in a cookie: the desktop app's (`MYCELIUM_UI_SESSION=memory`), which serves
 * the person on this machine. A cookie on 127.0.0.1 would go to every other
 * program listening on it too.
 */
export function heldInMemory(): boolean {
  return process.env.MYCELIUM_UI_SESSION === "memory";
}

/** How long a hub's answer about its sign-in is used before it's asked again. */
const DISCOVERED_FOR_MS = 60_000;
/** Never sealed into a cookie in memory mode; set only because the type asks for one. */
const UNUSED_SECRET = randomBytes(32).toString("hex");
const found = globalThis as { __myceliumOidc?: { at: number; cfg: OidcConfig | null } };

/**
 * The sign-in this UI server uses. The environment's when it names an issuer;
 * otherwise, in the desktop app, the one issuer the hub names at `/health`
 * (as `mycelium login` finds it), with the client the app passed in, which is
 * the CLI's and already signs in through this machine's loopback address.
 * Null when the hub asks for no sign-in, or names no single issuer.
 */
export async function resolveOidcConfig(): Promise<OidcConfig | null> {
  const configured = oidcConfig();
  if (configured || !heldInMemory()) return configured;
  const cached = found.__myceliumOidc;
  if (cached && Date.now() - cached.at < DISCOVERED_FOR_MS) return cached.cfg;
  const cfg = await discover();
  found.__myceliumOidc = { at: Date.now(), cfg };
  return cfg;
}

async function discover(): Promise<OidcConfig | null> {
  let issuers: unknown;
  try {
    const res = await fetch(`${getBackendUrl()}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    const auth = ((await res.json()) as { auth?: { enabled?: boolean; issuers?: unknown } }).auth;
    if (!auth?.enabled) return null;
    issuers = auth.issuers;
  } catch {
    return null;
  }
  const named = Array.isArray(issuers) ? issuers.filter((i): i is string => typeof i === "string" && !!i.trim()) : [];
  // Several issuers is not a choice to guess at: which one decides who the hub thinks you are.
  if (named.length !== 1) return null;
  const issuer = trimSlash(named[0].trim());
  return {
    issuer,
    internalIssuer: issuer,
    clientId: process.env.MYCELIUM_OIDC_CLIENT_ID?.trim() || "mycelium-cli",
    audience: process.env.MYCELIUM_OIDC_AUDIENCE?.trim() || undefined,
    scopes: process.env.MYCELIUM_OIDC_SCOPES?.trim() || "openid profile email",
    handleClaim: process.env.MYCELIUM_OIDC_HANDLE_CLAIM?.trim() || "preferred_username",
    sessionSecret: UNUSED_SECRET,
  };
}
