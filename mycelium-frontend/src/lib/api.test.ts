// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { deleteRoom } from "@/lib/api";

describe("deleteRoom", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
      }),
    );
  });

  it("encodes room names and accepts an empty 204 response", async () => {
    await deleteRoom("design review/é");

    expect(fetch).toHaveBeenCalledWith("/api/rooms/design%20review%2F%C3%A9", {
      method: "DELETE",
    });
  });
});
