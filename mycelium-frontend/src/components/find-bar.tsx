// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { ChevronDown, ChevronUp, History, Loader2, Search, X } from "lucide-react";
import { useMemo, useState, type RefObject } from "react";
import { CandidateList, Signature, type Candidate } from "@/components/composer-hints";
import { Tooltip } from "@/components/ui/tooltip";
import { FIND_SKIP } from "@/lib/dom-find";
import { hintAt, type Seen } from "@/lib/message-search";
import { cn } from "@/lib/utils";

interface Props {
  /** What it finds in, for the input's name: "Find in the channel". */
  label?: string;
  placeholder?: string;
  /** Whether the query is the hub's search grammar, with its field hints. Off
   *  where the bar finds words in what a view has drawn. */
  grammar?: boolean;
  /** What the count is a count of, on hover. */
  countAbout?: string;
  /** What the History button reaches, on hover. */
  historyAbout?: string;
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
  /** The search behind the bar (the room's messages, a thread's, the room's
   *  memories): how many match, whether that answer is in flight, and whether
   *  its panel is open. Absent where there is none. */
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

/** ⌘F's bar, the same in every view: a strip above what it finds in, not an
 *  overlay on it.
 *
 *  It takes the height it needs and the view moves down, because a bar that
 *  floats over the channel covers the newest thing said at the exact moment
 *  the reader is hunting through the older ones.
 *
 *  Over messages it speaks the hub's search grammar (`from:avery task:checkout
 *  after:2d`), with the composer's hints under it: a field name completes as it
 *  is typed, and a `field:` offers the values the room's messages carry. */
export function FindBar({
  label = "Find in the channel",
  placeholder = "Find  ·  from:  task:  after:",
  grammar = true,
  countAbout,
  historyAbout = "Every match in the room, threads included",
  query,
  onQueryChange,
  count,
  position,
  settling = false,
  onStep,
  onClose,
  inputRef,
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
    () => (grammar && hinting ? hintAt(query, cursor, seen, handles) : null),
    [grammar, hinting, query, cursor, seen, handles],
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
    <div data-slot="find-bar" {...{ [FIND_SKIP]: "" }} className="relative shrink-0 border-b border-border bg-surface">
      <div className="flex items-center gap-2 px-4 py-1.5">
        <Search aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          aria-label={label}
          placeholder={placeholder}
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
        <Tooltip content={countAbout ?? "Matches in what's shown here"}>
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
          <Tooltip content={history.failed ? "Hub unreachable" : historyAbout}>
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
