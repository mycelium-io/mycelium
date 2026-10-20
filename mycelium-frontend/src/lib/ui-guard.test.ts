// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { guardApi, hostAllowed, TOKEN_HEADER, TOKEN_PARAM } from "@/lib/ui-guard";

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
    // Sign-in starts with a navigation, which can carry nothing.
    expect(guardApi(req("/api/auth/login"), TOKEN)).toBeNull();
  });
});
