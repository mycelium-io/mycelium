// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { startTransition, useEffect, useState } from "react";

/** How many of the newest rows draw in the first frame, and how many more each frame after. */
export const FIRST_ROWS = 12;
export const ROWS_PER_FRAME = 10;

/**
 * A long list's newest rows first, then the rest a batch a frame, oldest at
 * the top. Building a busy room's whole channel in one commit held the window
 * for a beat on every switch; a batch a frame, in a transition, keeps it
 * answering clicks and keys while the rows above the fold fill in.
 *
 *   const { drawn, skipped, done } = useBatchedRows(rows, { ready, all: findOpen });
 *
 * `drawn` is the tail of `rows` to render, and `skipped` how many rows sit
 * above it, so a row can still look at the one before it (`rows[skipped + i - 1]`).
 * Nothing grows until `ready`. `all` draws every row at once, for a find or a
 * row to scroll to, whose target could be anywhere.
 */
export function useBatchedRows<T>(rows: T[], { ready, all = false }: { ready: boolean; all?: boolean }) {
  const [count, setCount] = useState(FIRST_ROWS);
  const drawn = all || count >= rows.length ? rows : rows.slice(-count);
  const done = drawn.length === rows.length;
  useEffect(() => {
    if (!ready || done) return;
    const frame = requestAnimationFrame(() => startTransition(() => setCount((n) => n + ROWS_PER_FRAME)));
    return () => cancelAnimationFrame(frame);
  }, [ready, done, drawn.length]);
  return { drawn, skipped: rows.length - drawn.length, done };
}
