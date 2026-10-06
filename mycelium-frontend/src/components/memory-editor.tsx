// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MarkdownEditorHandle } from "@fedoup/markdown-editor";
import { Check, Copy, Loader2, Pencil } from "lucide-react";
import { ApiError, createMemories, type Memory, type MemoryCreate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { TagInput } from "@/components/ui/tag-input";
import {
  DraftBanner,
  DraftLinks,
  FullscreenButton,
  MemoryBodyEditor,
  useBodyCursor,
  useFullscreen,
  type BodyMode,
} from "@/components/memory-body-editor";
import { useRoomMemories } from "@/lib/room-data";
import { useIsMac } from "@/lib/client-hooks";
import { clearDraft, draftId, loadDraft, saveDraft, type MemoryDraft } from "@/lib/memory-drafts";
import { fmtAgo } from "@/lib/metrics-format";
import { cn } from "@/lib/utils";

export { WikilinkDropdown } from "@/components/wikilink-dropdown";

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
  /** Opens another memory, from a link in the preview or the links list. */
  onNavigate?: (key: string) => void;
  /** More controls at the end of the editor's header (a tab's View toggle). */
  headerExtra?: React.ReactNode;
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

const sameTags = (a: string[], b: string[]) => a.length === b.length && a.every((t, i) => t === b[i]);

/**
 * Editing a memory: its body in the same editor new memories are written in,
 * its properties (tags, whether it can be embedded) beside it, and where it
 * stands (what changed, which links resolve) always in view. Full screen
 * (⌘⇧F) lifts the whole screen over the app; ⌘S saves. Unsaved edits are kept
 * in this browser as a draft, so a reload or a link followed mid-edit offers
 * them back the next time the memory is opened for editing.
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
  onNavigate,
  headerExtra,
}: Props) {
  const original = memory.content_text ?? (typeof memory.value === "string" ? memory.value : "");
  const originalTags = useMemo(() => memory.tags ?? [], [memory.tags]);
  const originalExpandable = memory.expandable ?? false;

  const [tags, setTags] = useState<string[]>(originalTags);
  const [expandable, setExpandable] = useState(originalExpandable);
  const [text, setText] = useState(original);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ message: string; conflict: boolean } | null>(null);
  const [copied, setCopied] = useState(false);
  const [mode, setMode] = useState<BodyMode>("write");
  const [generation, setGeneration] = useState(0);
  const [fullscreen, setFullscreen] = useFullscreen();
  const mac = useIsMac();

  const editorRef = useRef<MarkdownEditorHandle | null>(null);
  const cursor = useBodyCursor();

  // Dirty against what was opened, so undoing an edit by hand reads as clean.
  const dirty = text !== original || !sameTags(tags, originalTags) || expandable !== originalExpandable;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  // ── the draft kept in this browser ─────────────────────────────────────────
  const slot = draftId(roomName, memory.key);
  const [stored, setStored] = useState<MemoryDraft | null>(() => {
    const d = loadDraft(slot);
    return d && (d.body !== original || !sameTags(d.tags ?? [], originalTags) || (d.expandable ?? false) !== originalExpandable)
      ? d
      : null;
  });
  const saved = useRef(false);
  const pending = useRef<Omit<MemoryDraft, "savedAt"> | null>(null);
  useEffect(() => {
    // Offered back first; only once it is answered does this session's edit replace it.
    if (stored || saved.current) return;
    if (!dirty) {
      pending.current = null;
      clearDraft(slot);
      return;
    }
    pending.current = { body: text, tags, expandable, baseVersion: memory.version };
    const t = setTimeout(() => {
      if (pending.current) saveDraft(slot, pending.current);
    }, 400);
    return () => clearTimeout(t);
  }, [stored, dirty, slot, text, tags, expandable, memory.version]);
  // Leaving mid-edit (a link followed, the tab switched) keeps the last keystrokes too.
  useEffect(
    () => () => {
      if (pending.current && !saved.current) saveDraft(slot, pending.current);
    },
    [slot],
  );

  const restore = () => {
    if (!stored) return;
    setText(stored.body);
    setTags(stored.tags ?? []);
    setExpandable(stored.expandable ?? false);
    setGeneration(g => g + 1);
    if (mode === "preview") setMode("write");
    setStored(null);
  };

  const { memories } = useRoomMemories(roomName);
  const allKeys = useMemo(() => memories.map(m => m.key), [memories]);
  const keySet = useMemo(() => new Set(allKeys), [allKeys]);
  const expandableKeys = useMemo(() => memories.filter(m => m.expandable).map(m => m.key), [memories]);
  const roomTags = useMemo(() => [...new Set(memories.flatMap(m => m.tags ?? []))].sort(), [memories]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    const body = text;
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
      saved.current = true;
      clearDraft(slot);
      setSaving(false);
      onDirtyChange?.(false);
      onSaved();
    } catch (err) {
      setSaving(false);
      if (err instanceof ApiError && err.status === 409) {
        setError({
          message:
            "This memory was edited by someone else while you worked. Your text is still here: copy it, then reopen the memory to merge.",
          conflict: true,
        });
      } else {
        setError({ message: err instanceof Error ? err.message : "Save failed.", conflict: false });
      }
    }
  }, [saving, text, memory, roomName, actor, tags, expandable, slot, onDirtyChange, onSaved]);

  // ⌘S / ⌘↵ save from anywhere on the screen.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      if (e.key.toLowerCase() === "s" || e.key === "Enter") {
        e.preventDefault();
        void handleSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleSave]);

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard refused; the text is still in the editor.
    }
  };

  const crumbs = memory.key.split("/");

  const screen = (
    <div
      className={cn(
        "@container flex flex-col",
        fullscreen ? "fixed inset-0 z-50 bg-paper" : "h-full",
      )}
      role={fullscreen ? "dialog" : undefined}
      aria-modal={fullscreen || undefined}
      aria-label={fullscreen ? `Editing ${memory.key}` : undefined}
    >
      <header
        className={cn(
          "z-10 flex flex-shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-paper/95 px-5 py-2 backdrop-blur-sm",
          !fullscreen && "sticky top-0",
        )}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Pencil className="size-3.5 flex-shrink-0 text-accent" />
          <span className="min-w-0 truncate font-mono text-label text-text" title={memory.key}>
            {crumbs.map((part, i) => (
              <span key={i}>
                {i > 0 && <span className="text-faint">/</span>}
                {part}
              </span>
            ))}
          </span>
          <span className="flex-shrink-0 text-micro text-faint tabular">v{memory.version}</span>
          <span
            className={cn(
              "flex flex-shrink-0 items-center gap-1 text-micro",
              dirty ? "text-yellow" : "text-faint",
            )}
          >
            <span aria-hidden className={cn("size-1.5 rounded-full", dirty ? "bg-yellow" : "bg-border2")} />
            {dirty ? "Unsaved changes" : "No changes"}
          </span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1.5">
          {headerExtra && <div className="mr-1 flex items-center gap-2 text-micro text-muted-foreground">{headerExtra}</div>}
          <FullscreenButton on={fullscreen} onToggle={() => setFullscreen(v => !v)} />
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
            {saving && <Loader2 className="size-3.5 animate-spin" />}
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </header>

      {stored && (
        <DraftBanner
          draft={stored}
          note={
            stored.baseVersion !== undefined && stored.baseVersion !== memory.version
              ? `made on v${stored.baseVersion}; it's v${memory.version} now`
              : undefined
          }
          onRestore={restore}
          onDiscard={() => {
            clearDraft(slot);
            setStored(null);
          }}
        />
      )}

      {error && (
        <div role="alert" className="flex flex-shrink-0 items-center gap-3 border-b border-red/30 bg-red/5 px-5 py-2 text-label text-red">
          <span className="min-w-0 flex-1">{error.message}</span>
          {error.conflict && (
            <Button variant="outline" size="sm" onClick={() => void copyText()}>
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "Copied" : "Copy my text"}
            </Button>
          )}
        </div>
      )}

      <div
        className={cn(
          "grid grid-cols-1 gap-4 px-5 py-4 @2xl:grid-cols-[minmax(0,1fr)_240px]",
          fullscreen && "min-h-0 flex-1 overflow-y-auto @2xl:overflow-hidden",
        )}
      >
        <MemoryBodyEditor
          editorRef={editorRef}
          value={text}
          onChange={setText}
          cursor={cursor}
          mode={mode}
          onModeChange={setMode}
          keys={allKeys}
          expandableKeys={expandableKeys}
          generation={generation}
          onNavigate={onNavigate}
          autoFocus
          className={fullscreen ? "min-h-[60vh] @2xl:min-h-0" : undefined}
          bodyClassName={fullscreen ? undefined : "min-h-[320px]"}
        />

        <aside className={cn("flex min-w-0 flex-col gap-5", fullscreen && "@2xl:overflow-y-auto")}>
          <section className="flex flex-col gap-1.5">
            <h3 className="text-micro font-medium text-faint">Tags</h3>
            <TagInput
              value={tags}
              onChange={setTags}
              suggestions={roomTags}
              placeholder="Add tag…"
              ariaLabel="Memory tags"
            />
          </section>

          <section className="flex flex-col gap-1.5">
            <h3 className="text-micro font-medium text-faint">Embedding</h3>
            <label className="flex cursor-pointer select-none items-start gap-2">
              <input
                type="checkbox"
                checked={expandable}
                onChange={e => setExpandable(e.target.checked)}
                className="mt-0.5 rounded border-border text-accent accent-accent"
              />
              <span className="text-label text-text">
                Expandable
                <span className="block text-micro text-muted-foreground">
                  Other memories can embed it whole with <span className="font-mono">![[{memory.key}]]</span>.
                </span>
              </span>
            </label>
          </section>

          <DraftLinks text={text} keys={keySet} onNavigate={onNavigate} />

          <section className="flex flex-col gap-1 text-micro text-muted-foreground">
            <h3 className="font-medium text-faint">About</h3>
            <span>
              Written by <span className="text-text">{memory.created_by}</span>
            </span>
            {memory.updated_at && (
              <span>
                Last saved {fmtAgo(memory.updated_at)}
                {memory.updated_by && (
                  <>
                    {" "}by <span className="text-text">{memory.updated_by}</span>
                  </>
                )}
              </span>
            )}
            {memory.file_path && (
              <span className="truncate font-mono text-faint" title={memory.file_path}>
                {memory.file_path}
              </span>
            )}
          </section>
        </aside>
      </div>

      <footer
        className={cn(
          "flex flex-shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-5 py-1.5 text-micro text-faint",
          !fullscreen && "mt-auto",
        )}
      >
        <span className="flex items-center gap-1.5">
          <Kbd size="xs" tone="muted">{mac ? "⌘S" : "Ctrl+S"}</Kbd> save
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd size="xs" tone="muted">{mac ? "⌘⇧F" : "Ctrl+Shift+F"}</Kbd> {fullscreen ? "leave full screen" : "full screen"}
        </span>
        {fullscreen && (
          <span className="flex items-center gap-1.5">
            <Kbd size="xs" tone="muted">Esc</Kbd> back
          </span>
        )}
      </footer>
    </div>
  );

  return fullscreen && typeof document !== "undefined" ? createPortal(screen, document.body) : screen;
}
