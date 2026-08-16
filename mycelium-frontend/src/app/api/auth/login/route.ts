// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Start the Authorization Code + PKCE flow: stash the verifier/state in a
// short-lived httpOnly cookie and redirect the browser to the IdP.

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { oidcConfig } from "@/lib/auth-config";
import { endpoints, pkce, randomState, requestOrigin } from "@/lib/oidc";
import { seal, TX_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const cfg = oidcConfig();
  if (!cfg) {
    return NextResponse.json({ detail: "Browser OIDC login is not configured" }, { status: 400 });
  }

  const url = new URL(req.url);
  const origin = requestOrigin(req);
  const returnTo = sanitizeReturn(url.searchParams.get("return_to"));
  const redirectUri = `${origin}/api/auth/callback`;

  let ep;
  try {
    ep = await endpoints(cfg);
  } catch (e) {
    return loginError(origin, e instanceof Error ? e.message : "discovery failed");
  }

  const { verifier, challenge } = pkce();
  const state = randomState();
  const tx = await seal({ verifier, state, returnTo }, cfg.sessionSecret, 600);
  const jar = await cookies();
  jar.set(TX_COOKIE, tx, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 600,
  });

  const auth = new URL(ep.authorizationEndpoint);
  auth.searchParams.set("response_type", "code");
  auth.searchParams.set("client_id", cfg.clientId);
  auth.searchParams.set("redirect_uri", redirectUri);
  auth.searchParams.set("scope", cfg.scopes);
  auth.searchParams.set("state", state);
  auth.searchParams.set("code_challenge", challenge);
  auth.searchParams.set("code_challenge_method", "S256");
  return NextResponse.redirect(auth.toString());
}

/** Only ever return to a same-origin path — never an attacker-supplied URL. */
function sanitizeReturn(v: string | null): string {
  if (!v || !v.startsWith("/") || v.startsWith("//")) return "/";
  return v;
}

function loginError(origin: string, msg: string): Response {
  const to = new URL("/", origin);
  to.searchParams.set("auth_error", msg);
  return NextResponse.redirect(to.toString());
}
