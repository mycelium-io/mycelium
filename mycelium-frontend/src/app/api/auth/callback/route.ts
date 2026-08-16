// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Finish the flow: verify state, exchange the code for tokens, and seal them
// into the session cookie. Then bounce back to where login started.

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { oidcConfig } from "@/lib/auth-config";
import { claimsOf, endpoints, exchangeCode, handleFromClaims, requestOrigin } from "@/lib/oidc";
import { TX_COOKIE, unseal, writeSession, type Session } from "@/lib/session";

export const dynamic = "force-dynamic";

interface Tx {
  verifier: string;
  state: string;
  returnTo: string;
}

export async function GET(req: Request): Promise<Response> {
  const cfg = oidcConfig();
  if (!cfg) {
    return NextResponse.json({ detail: "Browser OIDC login is not configured" }, { status: 400 });
  }

  const url = new URL(req.url);
  const origin = requestOrigin(req);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const idpError = url.searchParams.get("error");

  const jar = await cookies();
  const txRaw = jar.get(TX_COOKIE)?.value;
  // The transaction cookie is single-use — clear it regardless of outcome.
  jar.set(TX_COOKIE, "", { path: "/", maxAge: 0 });

  if (idpError) return loginError(origin, `identity provider returned: ${idpError}`);
  if (!code || !state || !txRaw) return loginError(origin, "missing code or state");

  const tx = await unseal<Tx>(txRaw, cfg.sessionSecret);
  if (!tx || tx.state !== state) return loginError(origin, "state mismatch");

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
