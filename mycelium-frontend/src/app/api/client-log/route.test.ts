// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/client-log/route";

function post(body: unknown): Request {
  return new Request("http://ui/api/client-log", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/client-log", () => {
  afterEach(() => vi.restoreAllMocks());

  it("writes the page's line to this server's output as one line", async () => {
    const written = vi.spyOn(console, "error").mockImplementation(() => {});
    const res = await POST(post({ line: "stream handler failed\n  at handler (x.ts:1)" }));

    expect(res.status).toBe(204);
    expect(written).toHaveBeenCalledExactlyOnceWith("[page] stream handler failed |   at handler (x.ts:1)");
  });

  it("refuses an empty line, and caps a long one", async () => {
    const written = vi.spyOn(console, "error").mockImplementation(() => {});
    expect((await POST(post({ line: "  " }))).status).toBe(400);
    expect((await POST(post({}))).status).toBe(400);

    await POST(post({ line: "x".repeat(10_000) }));
    expect(String(written.mock.calls[0][0]).length).toBeLessThanOrEqual("[page] ".length + 4_000);
  });
});
