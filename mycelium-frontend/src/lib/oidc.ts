// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A small, dependency-light OIDC client for the Authorization Code + PKCE flow,
// mirroring the CLI's `oidc.py`. SERVER-SIDE only (route handlers): it fetches
// discovery and exchanges codes/refresh tokens over the network.

import { createHash, randomBytes } from "node:crypto";
import type { OidcConfig } from "./auth-config";

export function base64url(buf: Buffer | Uint8Array): string {
  return Buffer.from(buf)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

interface DiscoveryDoc {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}

export interface Endpoints {
  /** The public `iss` (what the browser reaches, what the token carries). */
  issuer: string;
  /** Browser-facing — the redirect target for login. */
  authorizationEndpoint: string;
  /** Server-facing — rewritten onto the internal host so the container can reach it. */
  tokenEndpoint: string;
  /** Browser-facing — optional RP-initiated logout. */
  endSessionEndpoint?: string;
}

const discoCache = new Map<string, { at: number; ep: Endpoints }>();
const DISCO_TTL_MS = 300_000;

/**
 * Discover endpoints from the internal issuer. Keycloak advertises PUBLIC URLs
 * (pinned by KC_HOSTNAME), so the token endpoint comes back as `localhost:…`
 * which the container can't reach — rewrite its base to the internal issuer.
 * Browser-facing URLs (authorization, end-session) are left public.
 */
export async function endpoints(cfg: OidcConfig): Promise<Endpoints> {
  const cached = discoCache.get(cfg.internalIssuer);
  if (cached && Date.now() - cached.at < DISCO_TTL_MS) return cached.ep;

  const url = `${cfg.internalIssuer}/.well-known/openid-configuration`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`OIDC discovery failed (${res.status}) at ${url}`);
  const d = (await res.json()) as DiscoveryDoc;

  const toInternal = (u: string): string =>
    u.startsWith(d.issuer) ? cfg.internalIssuer + u.slice(d.issuer.length) : u;

  const ep: Endpoints = {
    issuer: d.issuer,
    authorizationEndpoint: d.authorization_endpoint,
    tokenEndpoint: toInternal(d.token_endpoint),
    endSessionEndpoint: d.end_session_endpoint,
  };
  discoCache.set(cfg.internalIssuer, { at: Date.now(), ep });
  return ep;
}

/**
 * The browser-facing origin of a request. `new URL(req.url).origin` is unusable
 * here: the Next standalone server reports its bind address (`0.0.0.0:3000`), not
 * the host the browser actually used — which would send an unregistered
 * `redirect_uri` to the IdP. Trust the `Host` header (and forwarded variants
 * behind a proxy) instead.
 */
export function requestOrigin(req: Request): string {
  const h = req.headers;
  const proto = h.get("x-forwarded-proto") ?? new URL(req.url).protocol.replace(/:$/, "");
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? new URL(req.url).host;
  return `${proto}://${host}`;
}

export function pkce(): { verifier: string; challenge: string } {
  const verifier = base64url(randomBytes(32));
  const challenge = base64url(createHash("sha256").update(verifier).digest());
  return { verifier, challenge };
}

export function randomState(): string {
  return base64url(randomBytes(16));
}

export interface TokenSet {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  id_token?: string;
  scope?: string;
}

export function exchangeCode(
  cfg: OidcConfig,
  ep: Endpoints,
  code: string,
  redirectUri: string,
  verifier: string,
): Promise<TokenSet> {
  return tokenRequest(ep.tokenEndpoint, {
    grant_type: "authorization_code",
    code,
    client_id: cfg.clientId,
    redirect_uri: redirectUri,
    code_verifier: verifier,
  });
}

export function refreshTokens(cfg: OidcConfig, ep: Endpoints, refreshToken: string): Promise<TokenSet> {
  return tokenRequest(ep.tokenEndpoint, {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: cfg.clientId,
  });
}

async function tokenRequest(url: string, form: Record<string, string>): Promise<TokenSet> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(form).toString(),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`token endpoint ${res.status}: ${body.slice(0, 200)}`);
  }
  return (await res.json()) as TokenSet;
}

/** Decode a JWT's claims without verifying — the token is only used as a bearer
 *  the backend re-validates; here we read `preferred_username`/`exp` locally. */
export function claimsOf(jwt: string): Record<string, unknown> {
  const part = jwt.split(".")[1];
  if (!part) return {};
  try {
    const json = Buffer.from(part.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** The `@handle` a token resolves to: the configured claim, falling back to
 *  `preferred_username` then `sub`, normalized like stored handles. */
export function handleFromClaims(claims: Record<string, unknown>, claim: string): string {
  const raw = claims[claim] ?? claims["preferred_username"] ?? claims["sub"];
  return typeof raw === "string" ? raw.trim().replace(/^@/, "").toLowerCase() : "";
}
