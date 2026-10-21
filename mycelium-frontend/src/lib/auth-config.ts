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
import { fetchHealth } from "./hub-health";
import { tokenPromised } from "./ui-guard";

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
 * in a cookie: the desktop app's, which has a launch token (`lib/ui-guard.ts`).
 * A cookie on 127.0.0.1 would go to every other program listening on it too.
 * Promised counts, not only arrived: a launch whose token went missing still
 * never writes a cookie.
 */
export function heldInMemory(): boolean {
  return tokenPromised();
}

/** How long a hub's answer about its sign-in is used before it's asked again. */
const DISCOVERED_FOR_MS = 60_000;
/** Never sealed into a cookie in memory mode; set only because the type asks for one. */
const UNUSED_SECRET = randomBytes(32).toString("hex");
const found = globalThis as { __myceliumOidc?: { at: number; cfg: OidcConfig | null } };

/** What the hub says about its sign-in in its health: whether it asks for one, and whom it trusts. */
export interface HubSignIn {
  enabled: boolean;
  issuers: string[];
}

/** The hub's sign-in, from its health (`lib/hub-health.ts`). Null when the hub can't be read. */
export async function readHubSignIn(): Promise<HubSignIn | null> {
  try {
    const res = await fetchHealth();
    if (!res.ok) return null;
    const auth = ((await res.json()) as { auth?: { enabled?: boolean; issuers?: unknown } }).auth;
    const issuers = Array.isArray(auth?.issuers)
      ? auth.issuers.filter((i): i is string => typeof i === "string" && !!i.trim()).map(i => trimSlash(i.trim()))
      : [];
    return { enabled: Boolean(auth?.enabled), issuers };
  } catch {
    return null;
  }
}

/**
 * The sign-in this UI server uses. The environment's when it names an issuer;
 * otherwise, in the desktop app, the one issuer the hub names in its health
 * (as `mycelium login` finds it), with the client the app passed in, which is
 * the CLI's and already signs in through this machine's loopback address.
 * Null when the hub asks for no sign-in, or names no single issuer. A caller
 * that has just read the hub passes what it read, so the hub is asked once.
 */
export async function resolveOidcConfig(hub?: HubSignIn | null): Promise<OidcConfig | null> {
  const configured = oidcConfig();
  if (configured || !heldInMemory()) return configured;
  const cached = found.__myceliumOidc;
  if (hub === undefined && cached && Date.now() - cached.at < DISCOVERED_FOR_MS) return cached.cfg;
  const cfg = discovered(hub === undefined ? await readHubSignIn() : hub);
  found.__myceliumOidc = { at: Date.now(), cfg };
  return cfg;
}

/**
 * Why a hub that asks for sign-in can't be signed in to from here, in words
 * for the person looking at the sign-in screen. Null when it can, or when
 * this is not the desktop app (whose server is set up by its operator, and
 * the screen says what to set).
 */
export function whyNoSignIn(hub: HubSignIn | null): string | null {
  if (!hub?.enabled || !heldInMemory()) return null;
  if (hub.issuers.length === 0) {
    return "This hub needs you to sign in, but doesn't say where. Ask whoever runs the hub to set its identity provider.";
  }
  if (hub.issuers.length > 1) {
    return `This hub accepts sign-in from ${hub.issuers.length} identity providers, so the app can't tell which one to use. Ask whoever runs the hub to set one.`;
  }
  return null;
}

function discovered(hub: HubSignIn | null): OidcConfig | null {
  if (!hub?.enabled) return null;
  // Several issuers is not a choice to guess at: which one decides who the hub thinks you are.
  if (hub.issuers.length !== 1) return null;
  const issuer = hub.issuers[0];
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
