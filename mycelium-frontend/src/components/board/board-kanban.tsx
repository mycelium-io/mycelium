// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { lensOf, ownerOf, type LiveItem } from "@/lib/board/item";
import type { ItemGroup } from "@/lib/board/view";
import { humanize } from "@/lib/board/schema";
import { AgeTag, KindGlyph, OwnerChip, PriorityMeter, SourceTag, TtlBar, WorkLinks } from "./board-bits";

interface Props {
  groups: ItemGroup[];
  groupBy: string;
  now: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Dropping a card writes the column's value into the grouped field. */
  onMove: (item: LiveItem, field: string, value: string) => void;
}

/**
 * The same rows as columns. Grouping is by any inferred field, so "kanban" isn't
 * a status board that happens to exist — it's what the table looks like when you
 * pivot it, and dropping a card is just a write to that one field.
 */
export function BoardKanban({ groups, groupBy, now, selectedId, onSelect, onMove }: Props) {
  const [dragging, setDragging] = useState<LiveItem | null>(null);
  const [over, setOver] = useState<string | null>(null);

  return (
    <div className="flex h-full gap-3 overflow-x-auto px-5 py-4">
      {groups.map(group => {
        const active = over === group.key && dragging !== null;
        return (
          <div
            key={group.key}
            onDragOver={e => {
              e.preventDefault();
              setOver(group.key);
            }}
            onDragLeave={() => setOver(prev => (prev === group.key ? null : prev))}
            onDrop={e => {
              e.preventDefault();
              setOver(null);
              if (dragging) onMove(dragging, groupBy, group.key);
              setDragging(null);
            }}
            className={cn(
              "flex w-[268px] shrink-0 flex-col rounded-xl border bg-surface/40 transition-colors",
              active ? "border-accent/50 bg-accent-soft/40" : "border-border",
            )}
          >
            <header className="flex items-baseline gap-2 border-b border-hairline px-3 py-2">
              <span className="font-mono text-micro text-muted-foreground">
                {group.label}
              </span>
              <span className="tabular text-micro text-faint">{group.items.length}</span>
            </header>

            <div className="flex min-h-[120px] flex-1 flex-col gap-2 overflow-y-auto p-2">
              {group.items.map(item => (
                <article
                  key={item.id}
                  draggable
                  onDragStart={() => setDragging(item)}
                  onDragEnd={() => {
                    setDragging(null);
                    setOver(null);
                  }}
                  onClick={() => onSelect(item.id)}
                  className={cn(
                    "cursor-grab rounded-lg border bg-paper p-2.5 shadow-sm transition-colors active:cursor-grabbing",
                    item.id === selectedId ? "border-accent/50 ring-1 ring-accent/30" : "border-border hover:border-border2",
                    dragging?.id === item.id && "opacity-40",
                    lensOf(item) === "resolved" && "opacity-70",
                  )}
                >
                  <div className="flex items-start gap-2">
                    <KindGlyph item={item} className="mt-[1px]" />
                    <span className="min-w-0 flex-1 text-label leading-snug text-text">{item.title}</span>
                    <PriorityMeter item={item} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                    <OwnerChip handle={ownerOf(item)} live={item.fields.live === true} />
                    <WorkLinks item={item} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <SourceTag item={item} />
                    <span className="flex items-center gap-1.5">
                      <TtlBar item={item} now={now} />
                      <AgeTag item={item} now={now} />
                    </span>
                  </div>
                </article>
              ))}

              {group.items.length === 0 && (
                <div className="flex flex-1 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border/60 px-2 py-6 text-center text-micro text-faint">
                  <span>drop here to set</span>
                  <span className="font-mono text-muted-foreground">
                    {humanize(groupBy).toLowerCase()} = {group.key}
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
