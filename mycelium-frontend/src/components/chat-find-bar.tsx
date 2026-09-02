// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import type { RefObject } from "react";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";

interface Props {
  query: string;
  onQueryChange: (query: string) => void;
  /** Messages the query hits, and which of them the reader is standing on. */
  count: number;
  position: number | null;
  onStep: (delta: 1 | -1) => void;
  onClose: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
  /** True while the channel still has older pages it hasn't read. Find works on
   *  what is loaded, and says so rather than implying it searched the room. */
  partial: boolean;
}

/** The channel's find bar: a strip above the feed, not an overlay on it.
 *
 *  It takes the height it needs and the messages move down, because a bar that
 *  floats over the feed covers the newest thing said at the exact moment the
 *  reader is hunting through the older ones. */
export function ChatFindBar({
  query,
  onQueryChange,
  count,
  position,
  onStep,
  onClose,
  inputRef,
  partial,
}: Props) {
  const empty = query.trim().length === 0;
  const status = empty ? "" : count === 0 ? "No matches" : `${(position ?? 0) + 1}/${count}`;

  return (
    <div
      data-slot="chat-find-bar"
      className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-4 py-1.5"
    >
      <Search aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        aria-label="Find in the channel"
        placeholder="Find in the channel…"
        spellCheck={false}
        autoComplete="off"
        onChange={e => onQueryChange(e.target.value)}
        onKeyDown={e => {
          // Escape closes the bar rather than merely blurring it, so the key
          // that opened a search is the key that puts it away. Claiming the
          // event is what keeps the app-wide handler from taking it as a plain
          // "leave the input".
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
            return;
          }
          if (e.key === "Enter") {
            e.preventDefault();
            onStep(e.shiftKey ? -1 : 1);
          }
        }}
        className="min-w-0 flex-1 bg-transparent text-body text-text outline-none placeholder:text-faint"
      />
      <span
        aria-live="polite"
        className={`shrink-0 text-micro tabular ${count === 0 && !empty ? "text-red" : "text-muted-foreground"}`}
      >
        {status}
      </span>
      {partial && !empty && (
        <Tooltip content="Find reads the messages this channel has loaded. Scroll up to reach further back, or press / to search the room's whole history.">
          <span className="shrink-0 cursor-default text-micro text-faint">loaded only</span>
        </Tooltip>
      )}
      <div className="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          onClick={() => onStep(-1)}
          disabled={count === 0}
          aria-label="Previous match"
          className="rounded p-1 text-muted-foreground transition-colors enabled:hover:bg-hairline enabled:hover:text-text disabled:opacity-40"
        >
          <ChevronUp className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => onStep(1)}
          disabled={count === 0}
          aria-label="Next match"
          className="rounded p-1 text-muted-foreground transition-colors enabled:hover:bg-hairline enabled:hover:text-text disabled:opacity-40"
        >
          <ChevronDown className="size-3.5" />
        </button>
      </div>
      <Tooltip content="Enter for the next match, ⇧Enter for the previous">
        <Kbd size="xs" tone="muted" className="shrink-0">↵</Kbd>
      </Tooltip>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close find"
        className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
