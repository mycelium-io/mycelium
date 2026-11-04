// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Memory, MemorySummary } from "@/lib/api";
import { memoryTitle } from "@/lib/memory-preview";

/** A memory as the hub's light list would give it: named, with no text. For
 *  tests that describe a room by its memories and stub the list with them. */
export function summaryOf(memory: Partial<Memory> & { key: string }): MemorySummary {
  const { value, content_text: text, file_path: _path, ...rest } = memory; // eslint-disable-line @typescript-eslint/no-unused-vars -- dropped, as the hub drops it
  return {
    version: 1,
    created_by: "unknown",
    updated_at: "2026-11-03T10:00:00Z",
    ...rest,
    title: memoryTitle({ ...memory, value: value ?? {}, content_text: text } as Memory),
    structured: !!value && typeof value === "object" && !("text" in (value as object)),
  };
}
