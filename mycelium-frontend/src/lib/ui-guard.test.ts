// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { upstreamUrl } from "@/lib/backend";
import { guardApi, hostAllowed, MEDIA_PARAM, mediaSignatureOk, TOKEN_HEADER, TOKEN_PARAM } from "@/lib/ui-guard";
import { mediaSignature } from "@/lib/ui-token";

const TOKEN = "a".repeat(64);

function req(
  path: string,
  { method = "GET", headers = {} }: { method?: string; headers?: Record<string, string> } = {},
): Request {
  return new Request(`http://127.0.0.1:3717${path}`, {
    method,
    headers: { host: "127.0.0.1:3717", ...headers },
  });
}

describe("hostAllowed", () => {
  it("answers to loopback, an IP address and the configured name only", () => {
    expect(hostAllowed("127.0.0.1:3717", null)).toBe(true);
    expect(hostAllowed("localhost:3000", null)).toBe(true);
    expect(hostAllowed("192.168.1.20:3000", null)).toBe(true); // Docker by LAN address
    expect(hostAllowed("[::1]:3717", null)).toBe(true);
    expect(hostAllowed("mycelium.example.com", "mycelium.example.com")).toBe(true);
    // A page that rebinds its own name to this machine still sends that name.
    expect(hostAllowed("attacker.example:3717", null)).toBe(false);
    expect(hostAllowed("mycelium.example.com.attacker.example", "mycelium.example.com")).toBe(false);
    expect(hostAllowed(null, null)).toBe(false);
  });
});

describe("guardApi", () => {
  it("lets this app's own requests through", () => {
    expect(guardApi(req("/api/rooms"), null)).toBeNull();
    const json = { "content-type": "application/json", origin: "http://127.0.0.1:3717" };
    expect(guardApi(req("/api/rooms", { method: "POST", headers: json }), null)).toBeNull();
  });

  it("refuses a request from another site", async () => {
    const from = (origin: string) =>
      guardApi(req("/api/rooms", { method: "POST", headers: { origin, "content-type": "application/json" } }), null);
    expect(from("https://attacker.example")?.status).toBe(403);
    expect(from("null")?.status).toBe(403);
    // A form post or an image tag from another page, as fetch metadata says.
    const img = guardApi(req("/api/rooms", { headers: { "sec-fetch-site": "cross-site" } }), null);
    expect(img?.status).toBe(403);
  });

  it("refuses a name it doesn't serve, even on /api", () => {
    const rebound = new Request("http://attacker.example:3717/api/rooms", { headers: { host: "attacker.example:3717" } });
    expect(guardApi(rebound, null)?.status).toBe(421);
  });

  it("refuses a body that isn't JSON, except an upload and the mic's audio", () => {
    const post = (path: string, type: string) =>
      guardApi(req(path, { method: "POST", headers: { "content-type": type } }), null);
    expect(post("/api/rooms", "text/plain")?.status).toBe(415);
    expect(post("/api/rooms", "application/x-www-form-urlencoded")?.status).toBe(415);
    expect(post("/api/rooms/r/uploads", "multipart/form-data; boundary=x")).toBeNull();
    expect(post("/api/voice/sessions/s1", "application/octet-stream")).toBeNull();
    expect(post("/api/rooms", "application/octet-stream")?.status).toBe(415);
  });

  it("asks for this launch's token in the desktop app", () => {
    expect(guardApi(req("/api/rooms"), TOKEN)?.status).toBe(401);
    expect(guardApi(req("/api/rooms", { headers: { [TOKEN_HEADER]: "wrong" } }), TOKEN)?.status).toBe(401);
    expect(guardApi(req("/api/rooms", { headers: { [TOKEN_HEADER]: TOKEN } }), TOKEN)).toBeNull();
    // What can't set a header (an EventSource, an image) carries it in the URL.
    expect(guardApi(req(`/api/stream?${TOKEN_PARAM}=${TOKEN}`), TOKEN)).toBeNull();
    // Sign-in started as a navigation can carry nothing; one started from the
    // page (a POST) carries the token like everything else.
    expect(guardApi(req("/api/auth/login"), TOKEN)).toBeNull();
    expect(guardApi(req("/api/auth/callback"), TOKEN)).toBeNull();
    const post = { method: "POST", headers: { "content-type": "application/json" } };
    expect(guardApi(req("/api/auth/login", post), TOKEN)?.status).toBe(401);
  });

  it("lets a file be read with a signature for its own path, never another's", () => {
    const now = Math.floor(Date.now() / 1000);
    const exp = now + 900;
    const path = "/api/rooms/r/uploads/a.png";
    const media = `${exp}.${mediaSignature(TOKEN, path, exp)}`;
    expect(guardApi(req(`${path}?${MEDIA_PARAM}=${media}`), TOKEN)).toBeNull();
    // The same signature for any other file, or to write, is refused.
    expect(guardApi(req(`/api/rooms/r/uploads/b.png?${MEDIA_PARAM}=${media}`), TOKEN)?.status).toBe(401);
    expect(guardApi(req(`/api/rooms?${MEDIA_PARAM}=${media}`), TOKEN)?.status).toBe(401);
    const del = guardApi(req(`${path}?${MEDIA_PARAM}=${media}`, { method: "DELETE" }), TOKEN);
    expect(del?.status).toBe(401);
    // And it runs out.
    expect(mediaSignatureOk(media, path, TOKEN, exp + 1)).toBe(false);
    const far = now + 7200;
    expect(mediaSignatureOk(`${far}.${mediaSignature(TOKEN, path, far)}`, path, TOKEN, now)).toBe(false);
  });
});

describe("proxy matcher", () => {
  it("checks every /api path, whatever it ends in", async () => {
    const { config } = await import("@/proxy");
    // A path like /api/…/notes.txt is the hub's, not a static file the
    // extension exclusion below it is for.
    expect(config.matcher).toContain("/api/:path*");
  });
});

describe("upstreamUrl", () => {
  it("never passes the token or a media signature on to the hub", () => {
    const url = upstreamUrl(
      "http://hub:8000",
      `http://127.0.0.1:3717/api/rooms/r/uploads/a.png?download=1&${TOKEN_PARAM}=t&${MEDIA_PARAM}=1.ab`,
    );
    expect(url).toBe("http://hub:8000/api/rooms/r/uploads/a.png?download=1");
    expect(upstreamUrl("http://hub:8000", "http://127.0.0.1:3717/api/health")).toBe("http://hub:8000/health");
  });
});
