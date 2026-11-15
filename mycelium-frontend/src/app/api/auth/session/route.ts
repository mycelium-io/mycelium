// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the browser needs to decide whether to show the app or the sign-in
// screen: is the backend gate on, is OIDC configured here, and are we signed in.

import { NextResponse } from "next/server";
import { readHubSignIn, resolveOidcConfig, whyNoSignIn } from "@/lib/auth-config";
import { getBackendUrl } from "@/lib/backend";
import { bearer, getSession } from "@/lib/session";
import { isMockMode } from "@/mocks";

export const dynamic = "force-dynamic";

// The mock app has no identity provider, so `MYCELIUM_UI_MOCK_AUTH` stands in
// for each state the browser can meet: a gated hub signed in or not, and an
// open hub that offers sign-in.
const MOCK_AUTH: Record<string, object> = {
  "signed-in": { authRequired: true, oidcConfigured: true, signedIn: true, handle: "operator" },
  "signed-out": { authRequired: true, oidcConfigured: true, signedIn: false, handle: null },
  optional: { authRequired: false, oidcConfigured: true, signedIn: false, handle: null },
  // Signed in, but the short handle their sign-in gives is someone else's.
  "needs-handle": {
    authRequired: true,
    oidcConfigured: true,
    signedIn: true,
    handle: null,
    needsHandle: true,
    suggested: "avery.quinn",
  },
};

export async function GET(): Promise<Response> {
  const mock = isMockMode() ? MOCK_AUTH[process.env.MYCELIUM_UI_MOCK_AUTH ?? ""] : undefined;
  if (mock) return NextResponse.json(mock);
  // One read of the hub's health, at whichever path it answers, before the
  // session (which then finds the sign-in it names already known). If the hub
  // can't be read, don't trap the user behind a login screen.
  const hub = isMockMode() ? null : await readHubSignIn();
  const oidcConfigured = (await resolveOidcConfig(hub)) != null;
  const session = await getSession();
  const me = session ? await hubIdentity() : null;
  return NextResponse.json({
    // `authRequired` comes from the backend's own health auth block — the gate
    // is the source of truth, so the UI can't disagree with it.
    authRequired: Boolean(hub?.enabled),
    oidcConfigured,
    signInProblem: oidcConfigured ? null : whyNoSignIn(hub),
    signedIn: session != null,
    // The hub's handle for this sign-in, never the token's own claim: a
    // sign-in's claim is often an email, and the hub gives the person a short
    // handle instead (`services/identities.py`).
    handle: me ? me.handle : session && !session.handle.includes("@") ? session.handle : null,
    needsHandle: me?.needsHandle ?? false,
    suggested: me?.suggested ?? null,
  });
}

/** Who the hub says this sign-in is, or null when it can't be asked. */
async function hubIdentity(): Promise<{
  handle: string | null;
  needsHandle: boolean;
  suggested: string | null;
} | null> {
  const token = await bearer();
  if (!token) return null;
  try {
    const res = await fetch(`${getBackendUrl()}/api/whoami`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const me = (await res.json()) as { handle?: string | null; needs_handle?: boolean; suggested?: string | null };
    return { handle: me.handle ?? null, needsHandle: Boolean(me.needs_handle), suggested: me.suggested ?? null };
  } catch {
    return null;
  }
}
