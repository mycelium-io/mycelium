// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the browser needs to decide whether to show the app or the sign-in
// screen: is the backend gate on, is OIDC configured here, and are we signed in.

import { NextResponse } from "next/server";
import { oidcConfig } from "@/lib/auth-config";
import { getBackendUrl } from "@/lib/backend";
import { getSession } from "@/lib/session";
import { isMockMode } from "@/mocks";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const session = await getSession();
  return NextResponse.json({
    // `authRequired` comes from the backend's own /health auth block — the gate
    // is the source of truth, so the UI can't disagree with it.
    authRequired: await gateOn(),
    oidcConfigured: oidcConfig() != null,
    signedIn: session != null,
    handle: session?.handle ?? null,
  });
}

async function gateOn(): Promise<boolean> {
  if (isMockMode()) return false;
  try {
    const res = await fetch(`${getBackendUrl()}/health`, { cache: "no-store" });
    if (!res.ok) return false;
    const health = (await res.json()) as { auth?: { enabled?: boolean } };
    return Boolean(health.auth?.enabled);
  } catch {
    // If we can't reach the backend, don't trap the user behind a login screen.
    return false;
  }
}
