// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { EditorView } from "@codemirror/view";
import { MarkdownEditor, type MarkdownEditorHandle } from "@fedoup/markdown-editor";
import {
  Bold,
  Code,
  FileText,
  Folder,
  FolderPlus,
  Heading2,
  Italic,
  Link2,
  List,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { ApiError, createMemories } from "@/lib/api";
import { useRoomMemories, useRoomRevalidate } from "@/lib/room-data";
import { usePrincipal } from "@/components/current-user";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { TagInput } from "@/components/ui/tag-input";
import { WikilinkDropdown } from "@/components/memory-editor";
import { filterWikilinkCandidates, wikilinkDetector, type WikilinkMatch } from "@/lib/wikilink-completions";
import {
  BOARD_FOLDERS,
  cleanFolder,
  folderChoices,
  folderCounts,
  joinKey,
  keyProblem,
  slugify,
  treeSlice,
  type TreeSlice,
} from "@/lib/memory-location";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roomName: string;
  /** A title to start from, e.g. what followed `/memory` in the message box. */
  initialTitle?: string;
  /** The folder to start in, e.g. the one the memory pane has open. */
  initialFolder?: string;
  /** Called with the new memory's key once it is written. */
  onCreated?: (key: string) => void;
}

/**
 * Writing a new memory: a title, where it goes, and what it says.
 *
 * The body is the same Live Preview editor memories are edited in, so markdown
 * renders as it's typed, with a small toolbar and `[[` completion for links to
 * other memories. Beside it, the room's tree is drawn around the spot the
 * memory will take, so its place is seen before it's written.
 */
export function NewMemoryDialog({ open, onOpenChange, roomName, initialTitle = "", initialFolder = "context", onCreated }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid-cols-1 gap-0 overflow-hidden p-0 sm:max-w-4xl [&>*]:min-w-0">
        {/* Remounted per opening, so each starts from what it was opened with. */}
        {open && (
          <NewMemoryForm
            roomName={roomName}
            initialTitle={initialTitle}
            initialFolder={initialFolder}
            onDone={(key) => {
              onOpenChange(false);
              if (key) onCreated?.(key);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function NewMemoryForm({
  roomName,
  initialTitle,
  initialFolder,
  onDone,
}: {
  roomName: string;
  initialTitle: string;
  initialFolder: string;
  onDone: (key: string | null) => void;
}) {
  const principal = usePrincipal();
  const revalidate = useRoomRevalidate(roomName);
  const { memories } = useRoomMemories(roomName);
  const keys = useMemo(() => memories.map((m) => m.key), [memories]);

  const [title, setTitle] = useState(initialTitle);
  const [folder, setFolder] = useState(initialFolder);
  const [name, setName] = useState(slugify(initialTitle));
  const [nameTouched, setNameTouched] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasBody, setHasBody] = useState(false);

  const key = joinKey(folder, name);
  const problem = name ? keyProblem(key) : null;
  const existing = memories.find((m) => m.key === key) ?? null;
  const slice = useMemo(() => treeSlice(keys, key), [keys, key]);
  const choices = useMemo(() => folderChoices(keys).slice(0, 6), [keys]);
  const allFolders = useMemo(() => [...folderCounts(keys).keys()].sort(), [keys]);
  const topFolder = cleanFolder(folder).split("/")[0] ?? "";

  // ── the body ──────────────────────────────────────────────────────────────
  const editorRef = useRef<MarkdownEditorHandle | null>(null);
  const [wikilinkMatch, setWikilinkMatch] = useState<WikilinkMatch | null>(null);
  // Built once: a new array would reconfigure the editor mid-edit, and the
  // setter never changes.
  const extensions = useMemo(() => [wikilinkDetector(setWikilinkMatch)], [setWikilinkMatch]);
  const candidates = useMemo(
    () => (wikilinkMatch ? filterWikilinkCandidates(keys, wikilinkMatch.query) : []),
    [wikilinkMatch, keys],
  );
  const applyWikilink = useCallback(
    (target: string) => {
      const view = editorRef.current?.view;
      if (!view || !wikilinkMatch) return;
      const insert = `${wikilinkMatch.sigil}${target}]]`;
      const to = Math.max(view.state.selection.main.head, wikilinkMatch.from);
      view.dispatch({
        changes: { from: wikilinkMatch.from, to, insert },
        selection: { anchor: wikilinkMatch.from + insert.length },
      });
      setWikilinkMatch(null);
      view.focus();
    },
    [wikilinkMatch, setWikilinkMatch],
  );

  const create = useCallback(async () => {
    if (saving) return;
    const written = (editorRef.current?.getValue() ?? "").trim();
    const heading = title.trim();
    if (!name) return setError("Give it a name.");
    if (problem) return setError(problem);
    if (!heading && !written) return setError("Write something first.");
    // The title leads the memory as its heading, unless the body already has one.
    const body = heading && !/^#\s/.test(written) ? `# ${heading}\n\n${written}`.trim() : written;
    setSaving(true);
    setError(null);
    try {
      await createMemories(roomName, [
        {
          key,
          value: body,
          content_text: body,
          created_by: principal.trim() || "user",
          ...(tags.length > 0 && { tags }),
          // Replacing one on purpose: only the version this dialog saw.
          ...(existing && { base_version: existing.version }),
        },
      ]);
      revalidate();
      onDone(key);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Someone changed that memory just now. Pick another name, or open it to edit."
          : err instanceof Error
            ? err.message
            : "Couldn't save it.",
      );
      setSaving(false);
    }
  }, [saving, title, name, problem, roomName, key, principal, tags, existing, revalidate, onDone]);

  // ⌘↵ / Ctrl+↵ creates it from anywhere in the dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void create();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [create]);

  return (
    <>
      <div className="border-b border-border px-6 pt-5 pb-4">
        <DialogTitle className="text-ui font-semibold text-text">
          New memory in <span className="font-mono">{roomName}</span>
        </DialogTitle>
        <DialogDescription className="mt-1 text-label text-muted-foreground">
          Something the room should keep: a decision, how something works, where things stand. Everyone in the
          room can read it and find it by what it means.
        </DialogDescription>
      </div>

      <div className="grid min-h-0 grid-cols-1 md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="flex min-w-0 flex-col gap-4 px-6 py-5">
          <input
            autoFocus
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              if (!nameTouched) setName(slugify(e.target.value));
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !(e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                editorRef.current?.focus();
              }
            }}
            placeholder="What's this about?"
            aria-label="Title"
            className="w-full bg-transparent text-[1.35rem] font-semibold leading-tight text-text placeholder:text-faint focus:outline-none"
          />

          {/* Where it goes: a folder, then its name. */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {choices.map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFolder(f)}
                  className={cn(
                    "h-6 rounded-md border px-2 font-mono text-micro transition-colors",
                    topFolder === f && !cleanFolder(folder).includes("/")
                      ? "border-accent/50 bg-accent-soft text-accent"
                      : "border-border text-muted-foreground hover:border-border2 hover:text-text",
                  )}
                >
                  {f}/
                </button>
              ))}
            </div>
            <div className="flex min-w-0 items-center rounded-lg border border-border bg-bg font-mono text-label transition-colors focus-within:border-accent">
              <input
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
                list="new-memory-folders"
                aria-label="Folder"
                placeholder="folder"
                spellCheck={false}
                // Sized to what's typed, so the name follows the folder's slash.
                style={{ width: `calc(${Math.max(folder.length, 6)}ch + 1rem)` }}
                className="min-w-0 max-w-[50%] shrink-0 bg-transparent py-2 pl-3 text-muted-foreground outline-none placeholder:text-faint"
              />
              <span className="text-faint">/</span>
              <input
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setNameTouched(true);
                }}
                aria-label="Name"
                placeholder="name"
                spellCheck={false}
                className="min-w-0 flex-1 bg-transparent py-2 pr-3 text-text outline-none placeholder:text-faint"
              />
              <datalist id="new-memory-folders">
                {allFolders.map((f) => (
                  <option key={f} value={f} />
                ))}
              </datalist>
            </div>
            {problem ? (
              <p className="text-micro text-red">{problem}</p>
            ) : BOARD_FOLDERS.has(topFolder) ? (
              <p className="text-micro text-muted-foreground">
                Memories in <span className="font-mono">{topFolder}/</span> show up on the board. To hand someone
                work, <span className="font-mono">/task</span> in the message box files it with its own thread.
              </p>
            ) : null}
          </div>

          <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-bg focus-within:border-border2">
            <FormatBar editor={editorRef} />
            <div className="max-h-[320px] min-h-[200px] overflow-y-auto">
              <MarkdownEditor
                ref={editorRef}
                initialValue=""
                placeholder="Write it down. Markdown works, and [[ links to another memory."
                onChange={(next) => setHasBody(next.trim().length > 0)}
                extraExtensions={extensions}
                className="min-h-[200px] w-full px-4 py-3"
              />
            </div>
          </div>

          <TagInput value={tags} onChange={setTags} placeholder="Add tag…" ariaLabel="Tags" />
        </div>

        <aside className="border-t border-border bg-surface/40 px-5 py-5 md:border-l md:border-t-0">
          <p className="mb-3 text-micro font-medium text-faint">Where it goes</p>
          <TreePreview roomName={roomName} slice={slice} version={existing?.version ?? null} />
        </aside>
      </div>

      <div className="flex items-center gap-3 border-t border-border px-6 py-3">
        {error ? (
          <p role="alert" className="min-w-0 flex-1 truncate text-label text-red">
            {error}
          </p>
        ) : (
          <span className="flex flex-1 items-center gap-1.5 text-micro text-faint">
            <Kbd size="xs" tone="muted">⌘↵</Kbd> to save
          </span>
        )}
        <Button variant="ghost" size="sm" onClick={() => onDone(null)} disabled={saving}>
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={() => void create()}
          disabled={saving || !name || !!problem || (!title.trim() && !hasBody)}
        >
          {saving && <Loader2 className="size-3.5 animate-spin" />}
          {existing ? `Replace ${key}` : "Save memory"}
        </Button>
      </div>

      {typeof document !== "undefined" &&
        wikilinkMatch &&
        candidates.length > 0 &&
        createPortal(
          <WikilinkDropdown
            match={wikilinkMatch}
            candidates={candidates}
            onSelect={applyWikilink}
            onDismiss={() => setWikilinkMatch(null)}
          />,
          document.body,
        )}
    </>
  );
}

/**
 * The room's tree around the new memory: the folders down to its own, what
 * already sits beside it, and the memory itself, marked new (or, when the name
 * is taken, marked as replacing what's there).
 */
function TreePreview({ roomName, slice, version }: { roomName: string; slice: TreeSlice; version: number | null }) {
  const depth = slice.path.length;
  const row = "flex h-6 min-w-0 items-center gap-1.5 font-mono text-micro";
  const indent = (level: number) => ({ paddingLeft: `${level * 14}px` });
  return (
    <div className="flex flex-col">
      <div className={cn(row, "text-muted-foreground")}>
        <Folder className="size-3.5 shrink-0 text-faint" />
        <span className="truncate">{roomName}</span>
      </div>
      {slice.path.map((segment, i) => (
        <div key={i} className={cn(row, "text-muted-foreground")} style={indent(i + 1)}>
          {slice.existing[i] ? (
            <Folder className="size-3.5 shrink-0 text-accent/70" />
          ) : (
            <FolderPlus className="size-3.5 shrink-0 text-accent" />
          )}
          <span className="truncate">{segment}/</span>
          {!slice.existing[i] && <span className="rounded bg-accent-soft px-1 text-[10px] text-accent">new folder</span>}
        </div>
      ))}
      {slice.folders.map((f) => (
        <TreeRow key={`d-${f}`} icon={Folder} level={depth + 1} dim>
          {f}/
        </TreeRow>
      ))}
      {slice.moreFolders > 0 && (
        <TreeRow level={depth + 1} dim>
          + {slice.moreFolders} more {slice.moreFolders === 1 ? "folder" : "folders"}
        </TreeRow>
      )}
      <div
        className={cn(
          row,
          "-mx-1.5 my-0.5 rounded px-1.5",
          slice.exists ? "bg-yellow/10 text-text ring-1 ring-yellow/40" : "bg-accent-soft text-text ring-1 ring-accent/40",
        )}
        style={{ paddingLeft: `${(depth + 1) * 14 + 6}px` }}
      >
        <FileText className={cn("size-3.5 shrink-0", slice.exists ? "text-yellow" : "text-accent")} />
        <span className="min-w-0 truncate">{slice.name || "name"}</span>
        <span
          className={cn(
            "ml-auto shrink-0 rounded px-1 text-[10px]",
            slice.exists ? "bg-yellow/15 text-yellow" : "bg-accent-soft text-accent",
          )}
        >
          {slice.exists ? `replaces v${version ?? "?"}` : "new"}
        </span>
      </div>
      {slice.files.map((f) => (
        <TreeRow key={`f-${f}`} icon={FileText} level={depth + 1} dim>
          {f}
        </TreeRow>
      ))}
      {slice.moreFiles > 0 && (
        <TreeRow level={depth + 1} dim>
          + {slice.moreFiles} more
        </TreeRow>
      )}
    </div>
  );
}

function TreeRow({
  icon: Icon,
  level,
  dim,
  children,
}: {
  icon?: LucideIcon;
  level: number;
  dim?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn("flex h-6 min-w-0 items-center gap-1.5 font-mono text-micro", dim ? "text-faint" : "text-text")}
      style={{ paddingLeft: `${level * 14}px` }}
    >
      {Icon ? <Icon className="size-3.5 shrink-0 opacity-70" /> : <span className="w-3.5 shrink-0" />}
      <span className="truncate">{children}</span>
    </div>
  );
}

// ── the toolbar ────────────────────────────────────────────────────────────

/** Wrap the selection in `before`/`after`, or insert them around a placeholder. */
function wrap(view: EditorView, before: string, after: string, placeholder: string) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to);
  const text = selected || placeholder;
  view.dispatch({
    changes: { from, to, insert: `${before}${text}${after}` },
    selection: { anchor: from + before.length, head: from + before.length + text.length },
  });
  view.focus();
}

/** Start the line the cursor is on with `prefix` (a heading or a list item). */
function prefixLine(view: EditorView, prefix: string) {
  const line = view.state.doc.lineAt(view.state.selection.main.from);
  if (line.text.startsWith(prefix)) {
    view.focus();
    return;
  }
  view.dispatch({ changes: { from: line.from, insert: prefix } });
  view.focus();
}

const FORMATS: { label: string; icon: LucideIcon; keys?: string; run: (v: EditorView) => void }[] = [
  { label: "Heading", icon: Heading2, run: (v) => prefixLine(v, "## ") },
  { label: "Bold", icon: Bold, keys: "⌘B", run: (v) => wrap(v, "**", "**", "bold") },
  { label: "Italic", icon: Italic, keys: "⌘I", run: (v) => wrap(v, "_", "_", "italic") },
  { label: "Code", icon: Code, keys: "⌘E", run: (v) => wrap(v, "`", "`", "code") },
  { label: "Link to a memory", icon: Link2, run: (v) => wrap(v, "[[", "]]", "") },
  { label: "List", icon: List, run: (v) => prefixLine(v, "- ") },
];

function FormatBar({ editor }: { editor: React.RefObject<MarkdownEditorHandle | null> }) {
  // The shortcuts work while the editor has focus; the buttons for everyone else.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const view = editor.current?.view;
      if (!view || !view.hasFocus || !(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
      const format = { b: FORMATS[1], i: FORMATS[2], e: FORMATS[3] }[e.key.toLowerCase()];
      if (!format) return;
      e.preventDefault();
      format.run(view);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor]);

  return (
    <div className="flex items-center gap-0.5 border-b border-border px-1.5 py-1">
      {FORMATS.map((f) => (
        <button
          key={f.label}
          type="button"
          title={f.keys ? `${f.label} (${f.keys})` : f.label}
          aria-label={f.label}
          // Keep the editor's selection: a click on the bar must not blur it.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            const view = editor.current?.view;
            if (view) f.run(view);
          }}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <f.icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
