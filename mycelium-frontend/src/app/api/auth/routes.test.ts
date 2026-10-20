// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/backend", () => ({ getBackendUrl: () => "https://hub.example.com" }));
vi.mock("next/headers", () => ({
  cookies: () => {
    throw new Error("a cookie was used");
  },
}));

import * as callback from "@/app/api/auth/callback/route";
import * as login from "@/app/api/auth/login/route";
import { getSession } from "@/lib/session";

const ISSUER = "https://sso.example.com/realms/team";

/** The hub's `/health` and its issuer's discovery document; nothing else answers. */
function serve() {
  const token = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/health")) return Response.json({ auth: { enabled: true, issuers: [ISSUER] } });
      if (url.endsWith("/.well-known/openid-configuration")) {
        return Response.json({
          issuer: ISSUER,
          authorization_endpoint: `${ISSUER}/auth`,
          token_endpoint: `${ISSUER}/token`,
        });
      }
      token(url);
      return new Response("not here", { status: 404 });
    }),
  );
  return token;
}

const at = (path: string, init?: RequestInit) =>
  new Request(`http://127.0.0.1:3717${path}`, { ...init, headers: { host: "127.0.0.1:3717", ...init?.headers } });

describe("signing in from the desktop app's UI", () => {
  beforeEach(() => {
    const g = globalThis as Record<string, unknown>;
    for (const k of ["__myceliumOidc", "__myceliumSession", "__myceliumSignIns"]) delete g[k];
    vi.stubEnv("MYCELIUM_UI_SESSION", "memory");
    vi.stubEnv("MYCELIUM_OIDC_ISSUER", "");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("starts only when the app's page asks, never from a plain navigation", async () => {
    serve();
    // No GET: a link, a redirect or an image can't start a sign-in.
    expect("GET" in login).toBe(false);
    const res = await login.POST(at("/api/auth/login", { method: "POST", body: JSON.stringify({ return_to: "/room/x" }) }));
    const { url } = (await res.json()) as { url: string };
    const auth = new URL(url);
    expect(auth.origin + auth.pathname).toBe(`${ISSUER}/auth`);
    expect(auth.searchParams.get("client_id")).toBe("mycelium-cli");
    expect(auth.searchParams.get("redirect_uri")).toBe("http://127.0.0.1:3717/api/auth/callback");
  });

  it("finishes only a sign-in it started: an unknown state keeps nothing and asks the IdP nothing", async () => {
    const token = serve();
    const res = await callback.GET(at("/api/auth/callback?code=c&state=never-started"));
    expect(res.headers.get("location")).toContain("auth_error=state+mismatch");
    expect(token).not.toHaveBeenCalled();
    expect(await getSession()).toBeNull();
  });
});
