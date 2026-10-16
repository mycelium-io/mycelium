// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { ChevronDown, ChevronUp, History, Loader2, Search, X } from "lucide-react";
import { useMemo, useState, type RefObject } from "react";
import { CandidateList, Signature, type Candidate } from "@/components/composer-hints";
import { Tooltip } from "@/components/ui/tooltip";
import { hintAt, type Seen } from "@/lib/message-search";
import { cn } from "@/lib/utils";

interface Props {
  query: string;
  onQueryChange: (query: string) => void;
  /** Messages the query hits, and which of them the reader is standing on. */
  count: number;
  position: number | null;
  /** True while the count is for an earlier query than the one typed: it is
   *  left unsaid rather than flashing "No matches" between keystrokes. */
  settling?: boolean;
  onStep: (delta: 1 | -1) => void;
  onClose: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
  /** True while the channel still has older pages it hasn't read. Stepping
   *  works on what is loaded, and says so rather than implying it searched the
   *  room; History is what reaches the rest. */
  partial: boolean;
  /** The room-wide search behind the bar: how many messages in the whole
   *  history match, whether that answer is in flight, and whether its panel is
   *  open. Absent where there is no hub search (a test, a session shim). */
  history?: {
    total: number | null;
    loading: boolean;
    failed: boolean;
    open: boolean;
    onToggle: () => void;
    /** What the hub could not read in the query, as typed. */
    problems: string[];
  };
  /** Values the room's messages carry per field (the last answer's facets),
   *  and the roster, offered as the query's `field:` is typed. */
  seen?: Seen;
  handles?: string[];
}

/** The channel's find bar: a strip above the feed, not an overlay on it.
 *
 *  It takes the height it needs and the messages move down, because a bar that
 *  floats over the feed covers the newest thing said at the exact moment the
 *  reader is hunting through the older ones.
 *
 *  It speaks the hub's search grammar (`from:avery task:checkout after:2d`),
 *  with the composer's hints under it: a field name completes as it is typed,
 *  and a `field:` offers the values the room's messages actually carry. */
export function ChatFindBar({
  query,
  onQueryChange,
  count,
  position,
  settling = false,
  onStep,
  onClose,
  inputRef,
  partial,
  history,
  seen = {},
  handles = [],
}: Props) {
  const empty = query.trim().length === 0;
  const unsaid = empty || settling;
  const status = unsaid ? "" : count === 0 ? "No matches" : `${(position ?? 0) + 1}/${count}`;

  const [cursor, setCursor] = useState(0);
  const [hinting, setHinting] = useState(true);
  const [lit, setLit] = useState(-1);
  const hint = useMemo(
    () => (hinting ? hintAt(query, cursor, seen, handles) : null),
    [hinting, query, cursor, seen, handles],
  );
  const showCandidates = hint !== null && hint.candidates.length > 0;

  const accept = (candidate: Candidate) => {
    if (!hint) return;
    const insertion = candidate.open ? candidate.insert : `${candidate.insert} `;
    const next = `${query.slice(0, hint.start)}${insertion}${query.slice(hint.end).replace(/^\s+/, "")}`;
    const pos = hint.start + insertion.length;
    onQueryChange(next);
    setCursor(pos);
    setLit(-1);
    requestAnimationFrame(() => {
      const node = inputRef.current;
      if (!node || node.value !== next) return;
      node.focus();
      node.setSelectionRange(pos, pos);
    });
  };

  const track = (node: HTMLInputElement) => {
    setCursor(node.selectionStart ?? node.value.length);
    setHinting(true);
  };

  return (
    <div data-slot="chat-find-bar" className="relative shrink-0 border-b border-border bg-surface">
      <div className="flex items-center gap-2 px-4 py-1.5">
        <Search aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          aria-label="Find in the channel"
          placeholder="Find  ·  from:  task:  after:"
          spellCheck={false}
          autoComplete="off"
          onChange={e => {
            onQueryChange(e.target.value);
            track(e.target);
            setLit(-1);
          }}
          onSelect={e => track(e.currentTarget)}
          onBlur={() => setHinting(false)}
          onKeyDown={e => {
            if (showCandidates) {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setLit(h => (h + 1) % hint.candidates.length);
                return;
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setLit(h => (h <= 0 ? hint.candidates.length - 1 : h - 1));
                return;
              }
              // Tab always completes, to the first row if none is lit; Enter
              // completes only a row the reader moved to, and otherwise keeps
              // stepping through matches as it always has.
              if (e.key === "Tab" || (e.key === "Enter" && lit >= 0)) {
                e.preventDefault();
                accept(hint.candidates[Math.max(0, lit)]);
                return;
              }
              if (e.key === "Escape") {
                e.preventDefault();
                setHinting(false);
                return;
              }
            }
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
        <Tooltip
          content={
            partial
              ? "Matches among the messages loaded here. History searches the whole room."
              : "Matches in the channel. History lists them all, threads included."
          }
        >
          <span
            aria-live="polite"
            className={`shrink-0 cursor-default text-micro tabular ${count === 0 && !unsaid ? "text-red" : "text-muted-foreground"}`}
          >
            {status}
          </span>
        </Tooltip>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={() => onStep(-1)}
            disabled={count === 0}
            aria-label="Previous match"
            title="Previous (⇧Enter)"
            className="rounded p-1 text-muted-foreground transition-colors enabled:hover:bg-hairline enabled:hover:text-text disabled:opacity-40"
          >
            <ChevronUp className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onStep(1)}
            disabled={count === 0}
            aria-label="Next match"
            title="Next (Enter)"
            className="rounded p-1 text-muted-foreground transition-colors enabled:hover:bg-hairline enabled:hover:text-text disabled:opacity-40"
          >
            <ChevronDown className="size-3.5" />
          </button>
        </div>
        {history && !empty && (
          <Tooltip content={history.failed ? "Hub unreachable" : "Every match in the room, threads included"}>
            <button
              type="button"
              onClick={history.onToggle}
              aria-expanded={history.open}
              aria-label={`Search history${history.total !== null ? `, ${history.total} matches` : ""}`}
              className={cn(
                "flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-micro tabular transition-colors",
                history.failed
                  ? "text-red"
                  : history.open
                    ? "bg-accent-soft text-accent"
                    : "text-muted-foreground hover:bg-hairline hover:text-text",
              )}
            >
              {history.loading ? (
                <Loader2 aria-hidden className="size-3 animate-spin" />
              ) : (
                <History aria-hidden className="size-3" />
              )}
              {!history.failed && history.total !== null && history.total}
            </button>
          </Tooltip>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close find"
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <X className="size-3.5" />
        </button>
      </div>
      {history && history.problems.length > 0 && (
        <p className="px-4 pb-1.5 pl-[2.6rem] text-micro text-red">
          Not understood: {history.problems.join(", ")}
        </p>
      )}
      {(showCandidates || hint?.signature) && (
        <div className="absolute left-9 top-full z-30 mt-1 flex w-full max-w-md flex-col gap-1.5">
          {hint?.signature && !showCandidates && (
            <Signature
              label="Search field"
              head={hint.signature.head}
              slots={hint.signature.slots}
              active={hint.signature.active}
              about={hint.signature.about}
              completes={showCandidates}
            />
          )}
          {showCandidates && (
            <CandidateList
              label="Search suggestions"
              candidates={hint.candidates}
              highlight={lit}
              onPick={accept}
              onHover={setLit}
            />
          )}
        </div>
      )}
    </div>
  );
}
