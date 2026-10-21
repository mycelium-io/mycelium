// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { guardApi } from "@/lib/ui-guard";
import { GET } from "./route";

vi.mock("@/lib/session", () => ({ bearer: async () => null }));

describe("the /api proxy in mock mode", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("marks what a fixture answered, so a mock app can be told from a real one", async () => {
    // shotkit's --mock attaches to a running dev server only when it says this.
    vi.stubEnv("MYCELIUM_UI_MOCK", "1");
    const res = await GET(new Request("http://localhost/api/rooms"));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-mycelium-mock")).toBe("1");
  });
});

describe("the /api proxy in front of a hub elsewhere", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("reaches a hub that serves its own UI, and guards its /api, as that hub's own request", async () => {
    // The desktop app in client mode: its UI server on 127.0.0.1 proxies the
    // page's calls to a hub at a public name, whose own server runs the guard.
    vi.stubEnv("MYCELIUM_INTERNAL_API_URL", "https://hub.example.com");
    const sent: Request[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      sent.push(new Request(url, init));
      return Response.json({ status: "ok" });
    });
    const page = new Request("http://127.0.0.1:3717/api/rooms?mycelium-ui=launch-token", {
      headers: {
        host: "127.0.0.1:3717",
        origin: "http://127.0.0.1:3717",
        referer: "http://127.0.0.1:3717/room/a",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        accept: "application/json",
      },
    });

    const res = await GET(page);

    expect(res.status).toBe(200);
    const [upstream] = sent;
    expect(upstream.url).toBe("https://hub.example.com/api/rooms");
    for (const h of ["origin", "referer", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest"]) {
      expect(upstream.headers.get(h), h).toBeNull();
    }
    expect(upstream.headers.get("accept")).toBe("application/json");

    // The hub's own server, with its public name set, checks what arrived.
    vi.stubEnv("MYCELIUM_UI_HOST", "hub.example.com");
    const arrived = new Request(upstream.url, { headers: upstream.headers });
    arrived.headers.set("host", "hub.example.com");
    expect(guardApi(arrived, null, false)).toBeNull();
    // What used to arrive, with the page's origin, is refused as another site.
    arrived.headers.set("origin", "http://127.0.0.1:3717");
    expect(guardApi(arrived, null, false)?.status).toBe(403);
  });

  it("reads health from a backend's root, or from a hub that serves its own pages", async () => {
    vi.stubEnv("MYCELIUM_INTERNAL_API_URL", "https://hub.example.com");
    const asked: string[] = [];
    const hubWithPages = async (url: string) => {
      asked.push(url);
      return url.endsWith("/api/health")
        ? Response.json({ status: "ok" })
        : new Response("<html>not found</html>", { status: 404 });
    };
    vi.stubGlobal("fetch", hubWithPages);

    const res = await GET(new Request("http://127.0.0.1:3717/api/health"));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
    expect(asked).toEqual(["https://hub.example.com/health", "https://hub.example.com/api/health"]);

    // A backend reached directly answers at its root, in one request.
    asked.length = 0;
    vi.stubGlobal("fetch", async (url: string) => {
      asked.push(url);
      return Response.json({ status: "ok" });
    });
    expect((await GET(new Request("http://127.0.0.1:3717/api/health"))).status).toBe(200);
    expect(asked).toEqual(["https://hub.example.com/health"]);
  });
});
