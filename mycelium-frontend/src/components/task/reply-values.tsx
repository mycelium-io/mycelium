// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { PickRecord } from "@/lib/conductor-line";
import { SatisfactionBars } from "@/components/task/satisfaction-bars";

/** In a conductor run's thread, what a member's reply is drawn against. */
export interface ReplyContext {
  /** The pick that read this reply, and whose reply it is. */
  rated?: { record: PickRecord; member: string };
}

/**
 * A rating reply's options as bars, under its prose: how close each option
 * gets the member to its own ideal, by letter, with the reason beside it.
 * Drawn from the pick that read the reply, never from the reply's text.
 */
export function ReplyValues({ context = {} }: { context?: ReplyContext }) {
  const { rated } = context;
  if (!rated) return null;
  const { record, member } = rated;
  const rows = record.options
    .filter((o) => record.table[o.label]?.[member] !== undefined)
    .map((o) => ({
      key: o.label,
      // The letter alone; the result lists what each letter is.
      label: (
        <span className="font-mono" title={o.text}>
          {o.label}
        </span>
      ),
      placed: record.placed?.[o.label]?.[member],
      why: record.reasons?.[o.label]?.[member],
    }));
  if (!rows.some((r) => r.placed !== undefined)) return null;
  return (
    <div className="mb-1.5 mt-1">
      <SatisfactionBars
        label="How close each option gets them to their ideal"
        bar={record.threshold / 100}
        narrow
        rows={rows}
      />
    </div>
  );
}
