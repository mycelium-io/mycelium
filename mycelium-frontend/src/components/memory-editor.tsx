// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MarkdownEditor, type MarkdownEditorHandle } from "@fedoup/markdown-editor";
import { ApiError, createMemories, type Memory, type MemoryCreate } from "@/lib/api";
import { TagInput } from "@/components/ui/tag-input";
import { useRoomMemories } from "@/lib/room-data";
import {
  filterWikilinkCandidates,
  wikilinkDetector,
  type WikilinkMatch,
} from "@/lib/wikilink-completions";

interface Props {
  memory: Memory;
  roomName: string;
  /** Called after a successful save so the parent can exit edit mode. */
  onSaved: () => void;
  /** Called when the user cancels without saving. */
  onCancel: () => void;
  /** Acting-as handle (falls back to memory.created_by). */
  actor?: string;
  /** Reports whether the editor holds edits that have not been saved. */
  onDirtyChange?: (dirty: boolean) => void;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-micro uppercase tracking-wide text-faint">{label}</label>
      {children}
    </div>
  );
}

/** Read existing tags from the top-level `memory.tags` field. */
function extractTags(mem: Memory): string[] {
  return mem.tags ?? [];
}

/**
 * The memory's value when it carries fields beyond its prose, else `null`.
 *
 * The API returns every value as an object, so a plain memory arrives as
 * `{text}` and only a genuinely structured one has more — category entries
 * written by the CLI keep `logged_at` and `category`, and a JSON memory keeps
 * whatever shape it was given. This matches how the store decides whether to
 * persist `value` as frontmatter. Those extra fields have to be written back
 * untouched: `value` is managed, so a previous one is never carried forward.
 */
function structuredValue(mem: Memory): Record<string, unknown> | null {
  const v = mem.value;
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const fields = v as Record<string, unknown>;
  return Object.keys(fields).some(k => k !== "text") ? fields : null;
}

// ---------------------------------------------------------------------------
// Wikilink autocomplete dropdown
// ---------------------------------------------------------------------------

/**
 * Keyboard-navigable completion list rendered as a React portal in
 * `document.body`, bypassing any overflow/z-index constraints on the editor's
 * ancestor elements.
 */
function WikilinkDropdown({
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
  // React's idiomatic "reset when prop changes" — store previous candidates and
  // update in-render (a second render pass fires immediately, no layout effect).
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

// ---------------------------------------------------------------------------
// MemoryEditor
// ---------------------------------------------------------------------------

/**
 * Inline editor for a memory: a structured frontmatter panel (tags,
 * expandable) above a fedoup Live Preview body editor with wikilink
 * autocomplete rendered as a React portal.
 *
 * All edit state is seeded on mount, so callers must pass `key={memory.key}`
 * to get a fresh editor when they switch memories.
 */
export function MemoryEditor({
  memory,
  roomName,
  onSaved,
  onCancel,
  actor,
  onDirtyChange,
}: Props) {
  const [tags, setTags] = useState<string[]>(extractTags(memory));
  const [expandable, setExpandable] = useState(memory.expandable ?? false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wikilinkMatch, setWikilinkMatch] = useState<WikilinkMatch | null>(null);

  const editorRef = useRef<MarkdownEditorHandle | null>(null);

  // The body is uncontrolled (fedoup owns the CM6 state), so dirtiness is a
  // flag set on the first edit rather than a diff against the original text.
  const [dirty, setDirty] = useState(false);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const { memories } = useRoomMemories(roomName);
  const allKeys = useMemo(() => memories.map(m => m.key), [memories]);
  const expandableKeys = useMemo(
    () => memories.filter(m => m.expandable).map(m => m.key),
    [memories],
  );

  // Built once and never rebuilt: a new extension array would reconfigure CM6
  // mid-edit. Safe because the state setter identity is stable for the life of
  // the component.
  const extensions = useMemo(() => [wikilinkDetector(setWikilinkMatch)], []);

  const wikilinkCandidates = useMemo(() => {
    if (!wikilinkMatch) return [];
    const pool = wikilinkMatch.sigil === "![[" ? expandableKeys : allKeys;
    return filterWikilinkCandidates(pool, wikilinkMatch.query);
  }, [wikilinkMatch, allKeys, expandableKeys]);

  const applyWikilink = useCallback((key: string) => {
    const view = editorRef.current?.view;
    if (!view || !wikilinkMatch) return;
    const insert = `${wikilinkMatch.sigil}${key}]]`;
    // Replace through the live cursor rather than the position captured when
    // the match was made — a keystroke landing between the two would otherwise
    // be left stranded after the inserted link.
    const to = Math.max(view.state.selection.main.head, wikilinkMatch.from);
    view.dispatch({
      changes: { from: wikilinkMatch.from, to, insert },
      selection: { anchor: wikilinkMatch.from + insert.length },
    });
    setWikilinkMatch(null);
    view.focus();
  }, [wikilinkMatch]);

  const handleSave = useCallback(async () => {
    const body = editorRef.current?.getValue() ?? memory.content_text ?? "";
    setSaving(true);
    setError(null);

    const structured = structuredValue(memory);
    const item: MemoryCreate = {
      key: memory.key,
      value: structured ? { ...structured, text: body } : body,
      // Without this the store would derive the embedding text from the whole
      // value object, indexing a JSON dump instead of the prose.
      content_text: body,
      created_by: actor || memory.created_by,
      base_version: memory.version,
      ...(tags.length > 0 && { tags }),
      // Always sent, both true and false: the backend carries unmanaged
      // frontmatter forward across writes, so omitting the flag when unchecked
      // would leave a previously-set `expandable: true` on disk.
      meta: { expandable },
    };

    try {
      await createMemories(roomName, [item]);
      setDirty(false);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("This memory was edited by someone else. Reload to see the latest version.");
      } else {
        setError(err instanceof Error ? err.message : "Save failed.");
      }
    } finally {
      setSaving(false);
    }
  }, [memory, roomName, actor, tags, expandable, onSaved]);

  const body = memory.content_text ?? (typeof memory.value === "string" ? memory.value : "");

  return (
    <div className="flex flex-col gap-0 h-full">
      {/* Frontmatter panel */}
      <div className="border-b border-border px-5 py-4 space-y-4">
        <Field label="Key">
          <span className="font-mono text-label text-text break-all">{memory.key}</span>
        </Field>

        <Field label="Tags">
          <TagInput
            value={tags}
            onChange={next => { setTags(next); setDirty(true); }}
            placeholder="Add tag…"
            ariaLabel="Memory tags"
          />
        </Field>

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={expandable}
            onChange={e => { setExpandable(e.target.checked); setDirty(true); }}
            className="rounded border-border text-accent accent-accent"
          />
          <span className="text-label text-text">Expandable (allow transclusion)</span>
        </label>

        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-accent px-3 py-1.5 text-label font-medium text-white transition-opacity disabled:opacity-50 hover:opacity-90"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-border px-3 py-1.5 text-label font-medium text-text transition-colors hover:bg-hairline disabled:opacity-50"
          >
            Cancel
          </button>
          {error && (
            <span className="text-label text-red">{error}</span>
          )}
        </div>
      </div>

      {/* Body editor — uncontrolled; fedoup owns CM6 state */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <MarkdownEditor
          ref={editorRef}
          initialValue={body}
          onChange={() => setDirty(true)}
          extraExtensions={extensions}
          className="min-h-[200px] w-full px-5 py-4"
        />
      </div>

      {/* Wikilink dropdown — portal so overflow/z-index can't clip it */}
      {typeof document !== "undefined" && wikilinkMatch && wikilinkCandidates.length > 0 &&
        createPortal(
          <WikilinkDropdown
            match={wikilinkMatch}
            candidates={wikilinkCandidates}
            onSelect={applyWikilink}
            onDismiss={() => setWikilinkMatch(null)}
          />,
          document.body,
        )
      }
    </div>
  );
}
