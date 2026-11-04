// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Memory, MemorySummary } from "@/lib/api";
import { memorySummaryOf } from "@/lib/memory-preview";

/** A memory as the hub's light list would give it: named, with no text. For
 *  tests that describe a room by its memories and stub the list with them. */
export function summaryOf(memory: Partial<Memory> & { key: string }): MemorySummary {
  return memorySummaryOf({
    value: {},
    version: 1,
    created_by: "unknown",
    updated_at: "2026-11-03T10:00:00Z",
    ...memory,
  });
}
