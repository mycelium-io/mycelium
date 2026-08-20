// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarkdownEditor, type MarkdownEditorHandle } from "@fedoup/markdown-editor";
import { ApiError, createMemories, type Memory, type MemoryCreate } from "@/lib/api";
import { TagInput } from "@/components/ui/tag-input";
import { useRoomMemories } from "@/lib/room-data";
import { wikilinkCompletions } from "@/lib/wikilink-completions";

interface Props {
  memory: Memory;
  roomName: string;
  /** Called after a successful save so the parent can exit edit mode. */
  onSaved: () => void;
  /** Called when the user cancels without saving. */
  onCancel: () => void;
  /** Acting-as handle (falls back to memory.created_by). */
  actor?: string;
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

/** Extract `expandable` flag from the memory's value when it's an object. */
function extractExpandable(mem: Memory): boolean {
  if (!mem.value || typeof mem.value !== "object") return false;
  const v = mem.value as Record<string, unknown>;
  return v["expandable"] === true;
}

/**
 * Inline editor for a memory: a structured frontmatter panel (tags,
 * expandable) above a fedoup Live Preview body editor.
 *
 * The body is uncontrolled — fedoup owns the CM6 state. We pull the current
 * value via `editorRef.current.getValue()` at save time.
 */
export function MemoryEditor({ memory, roomName, onSaved, onCancel, actor }: Props) {
  const [tags, setTags] = useState<string[]>(extractTags(memory));
  const [expandable, setExpandable] = useState(extractExpandable(memory));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editorRef = useRef<MarkdownEditorHandle | null>(null);

  const { memories } = useRoomMemories(roomName);

  // Refs so the completion source always reads the latest keys even though the
  // CM6 extension is created once at editor mount (extraExtensions is not
  // reactive — fedoup applies it only during EditorState.create()).
  const allKeysRef = useRef<string[]>([]);
  const expandableKeysRef = useRef<string[]>([]);

  allKeysRef.current = useMemo(() => memories.map(m => m.key), [memories]);
  expandableKeysRef.current = useMemo(
    () => memories.filter(m => {
      if (!m.value || typeof m.value !== "object") return false;
      return (m.value as Record<string, unknown>)["expandable"] === true;
    }).map(m => m.key),
    [memories],
  );

  // Create the extension once; the getter closures read the current ref values
  // at completion time so async key loads are picked up automatically.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const extensions = useMemo(
    () => [wikilinkCompletions(() => allKeysRef.current, () => expandableKeysRef.current)],
    [],
  );

  // Keep tags/expandable in sync if the parent switches to a different memory.
  useEffect(() => {
    setTags(extractTags(memory));
    setExpandable(extractExpandable(memory));
    setError(null);
  }, [memory.key]);

  const handleSave = useCallback(async () => {
    const body = editorRef.current?.getValue() ?? memory.content_text ?? "";
    setSaving(true);
    setError(null);

    const item: MemoryCreate = {
      key: memory.key,
      value: body,
      created_by: actor || memory.created_by,
      base_version: memory.version,
      ...(tags.length > 0 && { tags }),
      ...(expandable && { meta: { expandable: true } }),
    };

    try {
      await createMemories(roomName, [item]);
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
            onChange={setTags}
            placeholder="Add tag…"
            ariaLabel="Memory tags"
          />
        </Field>

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={expandable}
            onChange={e => setExpandable(e.target.checked)}
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
          extraExtensions={extensions}
          className="min-h-[200px] w-full px-5 py-4"
        />
      </div>
    </div>
  );
}
