// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Start the Authorization Code + PKCE flow: stash the verifier/state (in a
// short-lived httpOnly cookie, or the desktop app's UI server's memory) and
// answer the IdP address the page then goes to.
//
// A POST from the app's own page, never a plain navigation, so it carries
// whatever proves a request comes from the app's pages. A sign-in started by
// anything else could be one a local program began with its own account, for
// the app to finish and quietly act as. Only the callback, which the IdP
// reaches by navigation, does without that, and it works only for a sign-in
// started here.

import { NextResponse } from "next/server";
import { resolveOidcConfig } from "@/lib/auth-config";
import { endpoints, pkce, randomState, requestOrigin } from "@/lib/oidc";
import { saveSignIn } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  const cfg = await resolveOidcConfig();
  if (!cfg) {
    return NextResponse.json({ detail: "Browser OIDC login is not configured" }, { status: 400 });
  }

  let body: { return_to?: unknown } = {};
  try {
    body = (await req.json()) as { return_to?: unknown };
  } catch {
    // No body: return to the start.
  }
  const origin = requestOrigin(req);
  const returnTo = sanitizeReturn(typeof body.return_to === "string" ? body.return_to : null);
  const redirectUri = `${origin}/api/auth/callback`;

  let ep;
  try {
    ep = await endpoints(cfg);
  } catch (e) {
    return NextResponse.json({ detail: e instanceof Error ? e.message : "discovery failed" }, { status: 502 });
  }

  const { verifier, challenge } = pkce();
  const state = randomState();
  await saveSignIn({ verifier, state, returnTo }, cfg.sessionSecret);

  const auth = new URL(ep.authorizationEndpoint);
  auth.searchParams.set("response_type", "code");
  auth.searchParams.set("client_id", cfg.clientId);
  auth.searchParams.set("redirect_uri", redirectUri);
  auth.searchParams.set("scope", cfg.scopes);
  auth.searchParams.set("state", state);
  auth.searchParams.set("code_challenge", challenge);
  auth.searchParams.set("code_challenge_method", "S256");
  return NextResponse.json({ url: auth.toString() });
}

/** Only ever return to a same-origin path — never an attacker-supplied URL. */
function sanitizeReturn(v: string | null): string {
  if (!v || !v.startsWith("/") || v.startsWith("//")) return "/";
  return v;
}
