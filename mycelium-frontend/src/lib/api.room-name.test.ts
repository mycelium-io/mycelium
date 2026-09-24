// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, expect, it, vi } from "vitest";
import { fetchRoom } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("encodes a spaced room name as one API path segment", async () => {
  const fetch = vi.fn(async () =>
    Response.json({
      name: "CE-Area Team",
      created_at: "2026-09-11T00:00:00Z",
      is_persistent: true,
    }),
  );
  vi.stubGlobal("fetch", fetch);

  await fetchRoom("CE-Area Team");

  expect(fetch).toHaveBeenCalledWith("/api/rooms/CE-Area%20Team", {
    cache: "no-store",
  });
});
