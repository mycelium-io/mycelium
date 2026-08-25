// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { cn } from "@/lib/utils";
import { ageMinutes, attentionFilterOf, type LiveItem } from "@/lib/board/item";
import { AgeTag, KindIcon, AssignmentChip, openableThread, SourceTag, ThreadChip, UpstreamChip, WorkLinks, kindColor } from "./board-cells";

interface Props {
  items: LiveItem[];
  now: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpenThread?: (episode: string) => void;
}

const BUCKETS: { label: string; within: number }[] = [
  { label: "Last hour", within: 60 },
  { label: "Today", within: 60 * 24 },
  { label: "This week", within: 60 * 24 * 7 },
  { label: "Earlier", within: Number.POSITIVE_INFINITY },
];

/**
 * The ledger, read as a ledger. Same rows, ordered by when they last moved —
 * the view that answers "what happened while I was away" without anyone
 * maintaining an activity feed.
 */
export function BoardTimeline({ items, now, selectedId, onSelect, onOpenThread }: Props) {
  const buckets = BUCKETS.map(bucket => ({
    ...bucket,
    items: items.filter(item => {
      const age = ageMinutes(item, now) ?? Number.POSITIVE_INFINITY;
      const index = BUCKETS.findIndex(b => age < b.within);
      return BUCKETS[index === -1 ? BUCKETS.length - 1 : index].label === bucket.label;
    }),
  })).filter(b => b.items.length > 0);

  return (
    <div className="px-5 py-4">
      {buckets.map(bucket => (
        <section key={bucket.label} className="mb-5">
          <h3 className="mb-2 font-mono text-micro text-muted-foreground">
            {bucket.label}
          </h3>
          <div className="relative pl-4">
            {/* The rail: one line the whole bucket hangs off. */}
            <span className="absolute inset-y-0 left-[5px] w-px bg-hairline" />
            {bucket.items.map(item => (
              <button
                key={item.id}
                onClick={() => {
                  onSelect(item.id);
                  const episode = openableThread(item);
                  if (episode) onOpenThread?.(episode);
                }}
                className={cn(
                  "relative flex w-full items-start gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors",
                  item.id === selectedId ? "bg-elevated ring-1 ring-border" : "hover:bg-hairline",
                  attentionFilterOf(item, now) === "resolved" && "opacity-65",
                )}
              >
                <span
                  className="absolute -left-[13px] top-3 size-[7px] rounded-full ring-2 ring-bg"
                  style={{ background: kindColor(item) }}
                />
                <KindIcon item={item} className="mt-[1px]" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-label text-text">{item.title}</span>
                    <AgeTag item={item} now={now} />
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <SourceTag item={item} />
                    <AssignmentChip item={item} now={now} />
                    <ThreadChip item={item} onOpen={onOpenThread} />
                    <WorkLinks item={item} />
          <UpstreamChip item={item} />
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
