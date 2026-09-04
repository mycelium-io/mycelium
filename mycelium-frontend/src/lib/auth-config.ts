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
 */
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
