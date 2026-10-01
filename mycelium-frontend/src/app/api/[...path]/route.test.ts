// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

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
