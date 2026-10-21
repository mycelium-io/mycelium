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
import * as session from "@/app/api/auth/session/route";
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
    // The desktop app's UI server: a launch token is promised.
    vi.stubEnv("MYCELIUM_UI_TOKEN_STDIN", "1");
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

  it("finds the sign-in of a hub that serves its own pages, which answers health only under /api", async () => {
    const asked: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        asked.push(url);
        if (url === "https://hub.example.com/api/health") {
          return Response.json({ auth: { enabled: true, issuers: [`${ISSUER}/`] } });
        }
        return new Response("not here", { status: 404 });
      }),
    );
    const body = await (await session.GET()).json();
    expect(body).toMatchObject({ authRequired: true, oidcConfigured: true, signInProblem: null, signedIn: false });
    // One read of the hub for the whole answer.
    expect(asked).toEqual(["https://hub.example.com/health", "https://hub.example.com/api/health"]);
  });

  it("says why it can't sign in to a hub that trusts more than one issuer, rather than offering nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ auth: { enabled: true, issuers: [ISSUER, "https://other.example.com"] } })),
    );
    const body = await (await session.GET()).json();
    expect(body).toMatchObject({ authRequired: true, oidcConfigured: false });
    expect(body.signInProblem).toContain("accepts sign-in from 2 identity providers");
  });

  it("doesn't trap anyone behind a sign-in screen when the hub can't be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));
    const body = await (await session.GET()).json();
    expect(body).toMatchObject({ authRequired: false, oidcConfigured: false, signInProblem: null });
  });
});
