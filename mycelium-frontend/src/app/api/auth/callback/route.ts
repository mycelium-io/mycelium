// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Finish the flow: verify state, exchange the code for tokens, and keep them as
// the session (a sealed cookie, or the desktop app's UI server's memory). Then
// bounce back to where login started.

import { NextResponse } from "next/server";
import { resolveOidcConfig } from "@/lib/auth-config";
import { claimsOf, endpoints, exchangeCode, handleFromClaims, requestOrigin } from "@/lib/oidc";
import { takeSignIn, writeSession, type Session } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const cfg = await resolveOidcConfig();
  if (!cfg) {
    return NextResponse.json({ detail: "Browser OIDC login is not configured" }, { status: 400 });
  }

  const url = new URL(req.url);
  const origin = requestOrigin(req);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const idpError = url.searchParams.get("error");

  // The sign-in under way is single-use: taken whatever happens next.
  const tx = state ? await takeSignIn(state, cfg.sessionSecret) : null;

  if (idpError) return loginError(origin, `identity provider returned: ${idpError}`);
  if (!code || !state) return loginError(origin, "missing code or state");
  if (!tx) return loginError(origin, "state mismatch");

  try {
    const ep = await endpoints(cfg);
    const redirectUri = `${origin}/api/auth/callback`;
    const t = await exchangeCode(cfg, ep, code, redirectUri, tx.verifier);
    const now = Math.floor(Date.now() / 1000);
    const session: Session = {
      access_token: t.access_token,
      refresh_token: t.refresh_token,
      expires_at: now + (t.expires_in ?? 300),
      handle: handleFromClaims(claimsOf(t.access_token), cfg.handleClaim),
    };
    await writeSession(session);
    return NextResponse.redirect(`${origin}${tx.returnTo || "/"}`);
  } catch (e) {
    return loginError(origin, e instanceof Error ? e.message : "token exchange failed");
  }
}

function loginError(origin: string, msg: string): Response {
  const to = new URL("/", origin);
  to.searchParams.set("auth_error", msg);
  return NextResponse.redirect(to.toString());
}
