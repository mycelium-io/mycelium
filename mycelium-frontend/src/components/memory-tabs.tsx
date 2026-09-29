// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { FileText, X } from "lucide-react";

/** A memory's name on its tab: the last part of its key (`cutover` for `decisions/cutover`). */
export function memoryTabLabel(key: string): string {
  return key.split("/").pop() || key;
}

/**
 * The memories open in the room, as tabs after Channel, Board and Network. The
 * open one takes the pane's color; each closes with its ×, or a middle click.
 */
export function MemoryTabs({
  keys,
  active,
  onSelect,
  onClose,
}: {
  keys: string[];
  active: string | null;
  onSelect: (key: string) => void;
  onClose: (key: string) => void;
}) {
  return (
    <>
      {keys.map(key => {
        const on = key === active;
        return (
          <div
            key={key}
            role="tab"
            aria-selected={on}
            title={key}
            onMouseDown={e => {
              if (e.button === 1) {
                e.preventDefault();
                onClose(key);
              }
            }}
            className={`group/tab relative -mb-px flex flex-shrink-0 items-center gap-1.5 border-r border-border pl-3 pr-1.5 text-label transition-colors ${
              on ? "bg-paper text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
            }`}
          >
            <button type="button" onClick={() => onSelect(key)} className="flex items-center gap-1.5">
              <FileText className="size-3.5 flex-shrink-0 text-faint" />
              <span className="max-w-40 truncate">{memoryTabLabel(key)}</span>
            </button>
            <button
              type="button"
              aria-label={`Close ${key}`}
              onClick={() => onClose(key)}
              className={`flex size-4 items-center justify-center rounded transition-opacity hover:bg-hairline ${
                on ? "opacity-100" : "opacity-0 group-hover/tab:opacity-100"
              }`}
            >
              <X className="size-3" />
            </button>
          </div>
        );
      })}
    </>
  );
}
