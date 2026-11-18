// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { PAGE_CSP, PAGE_ROUTES } from "@/lib/page-headers";

// Next matches a header rule's `source` as a path-to-regexp pattern; a source
// that is one regex group behaves like this anchored regex.
const matches = (path: string) => new RegExp(`^${PAGE_ROUTES}$`).test(path);

describe("page security headers", () => {
  it("are set on every page through the config", async () => {
    const rules = await nextConfig.headers!();
    const rule = rules.find((r) => r.source === PAGE_ROUTES);
    const header = (key: string) => rule?.headers.find((h) => h.key === key)?.value;
    expect(header("Content-Security-Policy")).toBe(PAGE_CSP);
    expect(header("X-Content-Type-Options")).toBe("nosniff");
    // It can't name the frames allowed, and would overrule them in an old browser.
    expect(header("X-Frame-Options")).toBeUndefined();
  });

  it("let only this machine and the published slides frame the app", () => {
    const ancestors = /frame-ancestors ([^;]+)/.exec(PAGE_CSP)?.[1].split(" ");
    expect(ancestors).toEqual(["'self'", "http://127.0.0.1:*", "http://localhost:*", "https://mycelium-io.github.io"]);
    expect(PAGE_CSP).toContain("object-src 'none'");
    expect(PAGE_CSP).toContain("base-uri 'none'");
  });

  it("cover the app's pages and leave the hub's responses alone", () => {
    expect(matches("/")).toBe(true);
    expect(matches("/room/checkout")).toBe(true);
    expect(matches("/settings/general")).toBe(true);
    expect(matches("/api/rooms/checkout/uploads/a.svg/raw")).toBe(false);
    expect(matches("/api/health")).toBe(false);
  });
});
