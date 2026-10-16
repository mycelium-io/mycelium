// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import type { WikilinkMatch } from "@/lib/wikilink-completions";

/**
 * Keyboard-navigable completion list rendered as a React portal in
 * `document.body`, bypassing any overflow/z-index constraints on the editor's
 * ancestor elements.
 */
export function WikilinkDropdown({
  match,
  candidates,
  onSelect,
  onDismiss,
}: {
  match: WikilinkMatch;
  candidates: string[];
  onSelect: (key: string) => void;
  onDismiss: () => void;
}) {
  // A fresh candidate list starts the highlight at the top. Comparing in render
  // rather than resetting in an effect, so no stale row is ever painted.
  const [prevCandidates, setPrevCandidates] = useState(candidates);
  const [activeIdx, setActiveIdx] = useState(0);
  if (prevCandidates !== candidates) {
    setPrevCandidates(candidates);
    setActiveIdx(0);
  }
  const listRef = useRef<HTMLDivElement>(null);

  // Keep the highlighted row visible when arrowing past the scroll fold.
  useEffect(() => {
    listRef.current?.children[activeIdx]?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  // Keyboard nav in capture phase so we intercept before CM6 keymaps.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault(); e.stopPropagation(); onDismiss();
      } else if (e.key === "ArrowDown") {
        e.preventDefault(); e.stopPropagation();
        setActiveIdx(i => Math.min(i + 1, candidates.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); e.stopPropagation();
        setActiveIdx(i => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        const chosen = candidates[activeIdx];
        if (chosen) { e.preventDefault(); e.stopPropagation(); onSelect(chosen); }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [candidates, activeIdx, onSelect, onDismiss]);

  // Dismiss on click outside.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (listRef.current && !listRef.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onDismiss]);

  if (candidates.length === 0) return null;

  return (
    <div
      ref={listRef}
      style={{ position: "fixed", left: match.x, top: match.y + 4, zIndex: 9999 }}
      className="min-w-[200px] max-w-xs max-h-52 overflow-y-auto rounded-md border border-border bg-background shadow-lg"
      onMouseDown={e => e.preventDefault()}
    >
      {candidates.map((k, i) => (
        <button
          key={k}
          type="button"
          className={`w-full text-left px-3 py-1.5 text-label font-mono truncate ${
            i === activeIdx ? "bg-accent text-white" : "text-text hover:bg-hairline"
          }`}
          onMouseDown={e => { e.preventDefault(); onSelect(k); }}
        >
          {k}
        </button>
      ))}
    </div>
  );
}
