// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FIRST_ROWS, useBatchedRows } from "./use-batched-rows";

const rows = Array.from({ length: 40 }, (_, i) => i);

describe("useBatchedRows", () => {
  it("draws the newest rows first, and holds them until ready", async () => {
    const { result, rerender } = renderHook(({ ready }) => useBatchedRows(rows, { ready }), {
      initialProps: { ready: false },
    });
    expect(result.current.drawn).toEqual(rows.slice(-FIRST_ROWS));
    expect(result.current.skipped).toBe(rows.length - FIRST_ROWS);
    expect(result.current.done).toBe(false);
    // Not ready: still the first batch a frame later.
    await new Promise((r) => requestAnimationFrame(r));
    expect(result.current.drawn).toHaveLength(FIRST_ROWS);

    rerender({ ready: true });
    await waitFor(() => expect(result.current.done).toBe(true), { timeout: 5000 });
    expect(result.current.drawn).toEqual(rows);
    expect(result.current.skipped).toBe(0);
  });

  it("draws every row at once when asked to", () => {
    const { result } = renderHook(() => useBatchedRows(rows, { ready: false, all: true }));
    expect(result.current.drawn).toEqual(rows);
    expect(result.current.done).toBe(true);
  });

  it("is done at once for a list shorter than the first batch", () => {
    const { result } = renderHook(() => useBatchedRows([1, 2, 3], { ready: true }));
    expect(result.current.drawn).toEqual([1, 2, 3]);
    expect(result.current.done).toBe(true);
  });
});
