// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { createHash } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import { base64url, handleFromClaims, pkce, requestOrigin } from "./oidc";
import { oidcConfig } from "./auth-config";

describe("base64url", () => {
  it("is url-safe and unpadded", () => {
    const out = base64url(Buffer.from([251, 255, 191, 0]));
    expect(out).not.toMatch(/[+/=]/);
  });
});

describe("pkce", () => {
  it("derives the S256 challenge from the verifier", () => {
    const { verifier, challenge } = pkce();
    expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/);
    const expected = base64url(createHash("sha256").update(verifier).digest());
    expect(challenge).toBe(expected);
  });
});

describe("handleFromClaims", () => {
  it("prefers the configured claim, normalized", () => {
    expect(handleFromClaims({ preferred_username: "@Demo" }, "preferred_username")).toBe("demo");
  });
  it("falls back to preferred_username, then sub", () => {
    expect(handleFromClaims({ sub: "uuid-1" }, "preferred_username")).toBe("uuid-1");
    expect(handleFromClaims({ preferred_username: "alice", sub: "uuid" }, "email")).toBe("alice");
  });
  it("is empty for a missing claim", () => {
    expect(handleFromClaims({}, "preferred_username")).toBe("");
  });
});

describe("requestOrigin", () => {
  const req = (headers: Record<string, string>) =>
    new Request("http://0.0.0.0:3000/api/auth/login", { headers });

  it("uses the Host header, not the bind address in req.url", () => {
    expect(requestOrigin(req({ host: "localhost:3000" }))).toBe("http://localhost:3000");
  });
  it("honors forwarded proto/host behind a proxy", () => {
    expect(
      requestOrigin(req({ "x-forwarded-proto": "https", "x-forwarded-host": "app.example.com" })),
    ).toBe("https://app.example.com");
  });
});

describe("oidcConfig", () => {
  const KEYS = [
    "MYCELIUM_OIDC_ISSUER",
    "MYCELIUM_OIDC_INTERNAL_ISSUER",
    "MYCELIUM_OIDC_CLIENT_ID",
    "MYCELIUM_OIDC_AUDIENCE",
    "AUTH_SESSION_SECRET",
  ];
  afterEach(() => KEYS.forEach((k) => delete process.env[k]));

  it("is null (off) until issuer + session secret are both set", () => {
    expect(oidcConfig()).toBeNull();
    process.env.MYCELIUM_OIDC_ISSUER = "http://localhost:8080/realms/mycelium";
    expect(oidcConfig()).toBeNull(); // secret still missing
  });

  it("resolves, trims slashes, and defaults internalIssuer to issuer", () => {
    process.env.MYCELIUM_OIDC_ISSUER = "http://localhost:8080/realms/mycelium/";
    process.env.AUTH_SESSION_SECRET = "s3cret";
    const cfg = oidcConfig();
    expect(cfg?.issuer).toBe("http://localhost:8080/realms/mycelium");
    expect(cfg?.internalIssuer).toBe("http://localhost:8080/realms/mycelium");
    expect(cfg?.clientId).toBe("mycelium-web");
    expect(cfg?.handleClaim).toBe("preferred_username");
  });

  it("keeps a distinct internal issuer for the containerized server", () => {
    process.env.MYCELIUM_OIDC_ISSUER = "http://localhost:8080/realms/mycelium";
    process.env.MYCELIUM_OIDC_INTERNAL_ISSUER = "http://keycloak:8080/realms/mycelium";
    process.env.AUTH_SESSION_SECRET = "s3cret";
    expect(oidcConfig()?.internalIssuer).toBe("http://keycloak:8080/realms/mycelium");
  });
});
