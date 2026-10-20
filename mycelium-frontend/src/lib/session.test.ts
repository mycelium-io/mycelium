// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/backend", () => ({ getBackendUrl: () => "https://hub.example.com" }));
// The desktop app's UI server never touches a cookie: any use of one fails the test.
vi.mock("next/headers", () => ({
  cookies: () => {
    throw new Error("a cookie was used");
  },
}));

import { resolveOidcConfig } from "@/lib/auth-config";
import { clearSession, getSession, saveSignIn, takeSignIn, writeSession } from "@/lib/session";

/** The hub's `/health`, as the UI server reads it. */
function hubSays(auth: object | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(auth ? { auth } : {}), { status: 200 })),
  );
}

const forget = () => {
  const g = globalThis as Record<string, unknown>;
  delete g.__myceliumOidc;
  delete g.__myceliumSession;
  delete g.__myceliumSignIns;
};

describe("the desktop app's UI server signing in to its hub", () => {
  beforeEach(() => {
    forget();
    // The desktop app's UI server: a launch token is promised.
    vi.stubEnv("MYCELIUM_UI_TOKEN_STDIN", "1");
    vi.stubEnv("MYCELIUM_OIDC_ISSUER", "");
    vi.stubEnv("MYCELIUM_OIDC_CLIENT_ID", "");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("signs in against the one issuer the hub names, with the CLI's client", async () => {
    hubSays({ enabled: true, issuers: ["https://sso.example.com/realms/team/"] });
    const cfg = await resolveOidcConfig();
    expect(cfg?.issuer).toBe("https://sso.example.com/realms/team");
    expect(cfg?.clientId).toBe("mycelium-cli");
  });

  it("asks for no sign-in where the hub's gate is off, or it names no single issuer", async () => {
    hubSays({ enabled: false, issuers: ["https://sso.example.com/realms/team"] });
    expect(await resolveOidcConfig()).toBeNull();
    forget();
    hubSays({ enabled: true, issuers: ["https://a.example.com", "https://b.example.com"] });
    expect(await resolveOidcConfig()).toBeNull();
  });

  it("keeps the sign-in in its own memory, never in a cookie", async () => {
    hubSays({ enabled: true, issuers: ["https://sso.example.com/realms/team"] });
    expect(await getSession()).toBeNull();
    await writeSession({ access_token: "t", expires_at: 9e9, handle: "julia" });
    expect((await getSession())?.handle).toBe("julia");
    await clearSession();
    expect(await getSession()).toBeNull();
  });

  it("finishes a sign-in once, and only for the state it started with", async () => {
    hubSays({ enabled: true, issuers: ["https://sso.example.com/realms/team"] });
    await saveSignIn({ verifier: "v", state: "s1", returnTo: "/room/x" }, "unused");
    expect(await takeSignIn("other", "unused")).toBeNull();
    expect((await takeSignIn("s1", "unused"))?.returnTo).toBe("/room/x");
    expect(await takeSignIn("s1", "unused")).toBeNull();
  });
});
