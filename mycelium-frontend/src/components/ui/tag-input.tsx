// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

const norm = (s: string) => s.trim().replace(/^@/, "").toLowerCase();

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  /** Known values to autocomplete from (e.g. existing team slugs). */
  suggestions?: string[];
  placeholder?: string;
  ariaLabel?: string;
}

/** Chip/tag input: type a value and Enter (or comma) to add it, Backspace on an
 *  empty field removes the last, and matching known values surface as clickable
 *  suggestions. Values are normalized to lowercase slugs. */
export function TagInput({ value, onChange, suggestions = [], placeholder, ariaLabel }: Props) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const add = (raw: string) => {
    const t = norm(raw);
    if (t && !value.includes(t)) onChange([...value, t]);
    setDraft("");
  };

  const matches = useMemo(() => {
    const d = norm(draft);
    return suggestions.filter((s) => !value.includes(s) && (d === "" || s.includes(d))).slice(0, 8);
  }, [suggestions, value, draft]);

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      if (draft.trim()) add(draft);
    } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  // Commits the pending draft on blur, capturing text typed but not
  // submitted with Enter.
  const onBlur = () => {
    if (draft.trim()) add(draft);
  };

  return (
    <div>
      <div
        className="flex flex-wrap items-center gap-1.5 border border-border bg-bg px-2 py-1.5 transition-colors focus-within:border-accent"
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((t) => (
          <span
            key={t}
            className="flex items-center gap-1 rounded bg-surface px-1.5 py-0.5 font-mono text-micro text-text"
          >
            {t}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onChange(value.filter((v) => v !== t));
              }}
              aria-label={`Remove ${t}`}
              className="text-muted-foreground hover:text-text"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
          placeholder={value.length === 0 ? placeholder : ""}
          aria-label={ariaLabel}
          className="min-w-[8ch] flex-1 bg-transparent font-mono text-micro text-text outline-none placeholder:text-muted-foreground"
        />
      </div>
      {matches.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {matches.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="rounded border border-border px-1.5 py-0.5 font-mono text-micro text-muted-foreground hover:bg-surface hover:text-text transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
