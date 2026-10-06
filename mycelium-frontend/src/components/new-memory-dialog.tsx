// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MarkdownEditorHandle } from "@fedoup/markdown-editor";
import { FileText, Folder, FolderPlus, Loader2, type LucideIcon } from "lucide-react";
import { ApiError, createMemories } from "@/lib/api";
import { useRoomMemories, useRoomRevalidate } from "@/lib/room-data";
import { usePrincipal } from "@/components/current-user";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
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
import { useIsMac } from "@/lib/client-hooks";
import { clearDraft, draftId, loadDraft, saveDraft, type MemoryDraft } from "@/lib/memory-drafts";
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
 * The body is the same editor memories are edited in (`MemoryBodyEditor`), so
 * markdown renders as it's typed, with a toolbar, `[[` completion and a
 * preview. Beside it, the room's tree is drawn around the spot the memory will
 * take, so its place is seen before it's written. Full screen (⌘⇧F) gives the
 * body the whole window; what's written is kept in this browser until it's
 * saved, so a dialog closed by accident offers it back next time.
 */
export function NewMemoryDialog({ open, onOpenChange, roomName, initialTitle = "", initialFolder = "context", onCreated }: Props) {
  const [fullscreen, setFullscreen] = useFullscreen(open);
  const [hasContent, setHasContent] = useState(false);
  const close = () => {
    setFullscreen(false);
    onOpenChange(false);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next, details) => {
        if (next) return onOpenChange(true);
        // Esc steps out of full screen first, and a stray click outside
        // doesn't throw away something half written.
        if ((details.reason === "escape-key" && fullscreen) || (details.reason === "outside-press" && hasContent)) {
          details.cancel();
          if (details.reason === "escape-key") setFullscreen(false);
          return;
        }
        close();
      }}
    >
      <DialogContent
        className={cn(
          "flex flex-col gap-0 overflow-hidden p-0 [&>*]:min-w-0",
          fullscreen
            ? "top-0 left-0 h-dvh w-screen max-w-none translate-x-0 translate-y-0 rounded-none ring-0 sm:max-w-none data-open:zoom-in-100"
            : "max-h-[calc(100dvh-2rem)] sm:max-w-4xl",
        )}
      >
        {/* Remounted per opening, so each starts from what it was opened with. */}
        {open && (
          <NewMemoryForm
            roomName={roomName}
            initialTitle={initialTitle}
            initialFolder={initialFolder}
            fullscreen={fullscreen}
            onToggleFullscreen={() => setFullscreen((v) => !v)}
            onContentChange={setHasContent}
            onDone={(key) => {
              close();
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
  fullscreen,
  onToggleFullscreen,
  onContentChange,
  onDone,
}: {
  roomName: string;
  initialTitle: string;
  initialFolder: string;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onContentChange: (has: boolean) => void;
  onDone: (key: string | null) => void;
}) {
  const mac = useIsMac();
  const principal = usePrincipal();
  const revalidate = useRoomRevalidate(roomName);
  const { memories } = useRoomMemories(roomName);
  const keys = useMemo(() => memories.map((m) => m.key), [memories]);

  const [title, setTitle] = useState(initialTitle);
  const [folder, setFolder] = useState(initialFolder);
  const [name, setName] = useState(slugify(initialTitle));
  const [nameTouched, setNameTouched] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [expandable, setExpandable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const hasBody = text.trim().length > 0;

  const key = joinKey(folder, name);
  const problem = name ? keyProblem(key) : null;
  const existing = memories.find((m) => m.key === key) ?? null;
  const slice = useMemo(() => treeSlice(keys, key), [keys, key]);
  const choices = useMemo(() => folderChoices(keys).slice(0, 6), [keys]);
  const allFolders = useMemo(() => [...folderCounts(keys).keys()].sort(), [keys]);
  const topFolder = cleanFolder(folder).split("/")[0] ?? "";
  const keySet = useMemo(() => new Set(keys), [keys]);
  const expandableKeys = useMemo(() => memories.filter((m) => m.expandable).map((m) => m.key), [memories]);
  const roomTags = useMemo(() => [...new Set(memories.flatMap((m) => m.tags ?? []))].sort(), [memories]);

  // ── the body ──────────────────────────────────────────────────────────────
  const editorRef = useRef<MarkdownEditorHandle | null>(null);
  const cursor = useBodyCursor();
  const [mode, setMode] = useState<BodyMode>("write");
  const [generation, setGeneration] = useState(0);

  // ── what's written, kept in this browser until it's saved ──────────────────
  const slot = draftId(roomName, null);
  const [stored, setStored] = useState<MemoryDraft | null>(() => {
    const d = loadDraft(slot);
    return d && (d.body.trim() || d.title?.trim()) ? d : null;
  });
  const hasContent = title.trim() !== initialTitle.trim() || hasBody || tags.length > 0;
  useEffect(() => onContentChange(hasContent), [hasContent, onContentChange]);
  const saved = useRef(false);
  const pending = useRef<Omit<MemoryDraft, "savedAt"> | null>(null);
  useEffect(() => {
    // An earlier draft is offered back first; this one only replaces it once that's answered.
    if (stored || saved.current || !hasContent) return;
    pending.current = { body: text, title, folder, name, tags, expandable };
    const t = setTimeout(() => {
      if (pending.current) saveDraft(slot, pending.current);
    }, 400);
    return () => clearTimeout(t);
  }, [stored, hasContent, slot, text, title, folder, name, tags, expandable]);
  // Closed by Esc, a click outside or the corner's ×: keep the last keystrokes too.
  useEffect(
    () => () => {
      if (pending.current && !saved.current) saveDraft(slot, pending.current);
    },
    [slot],
  );
  /** Cancel means it: nothing is kept. */
  const discard = () => {
    saved.current = true;
    clearDraft(slot);
    onDone(null);
  };

  const restore = () => {
    if (!stored) return;
    setText(stored.body);
    setTitle(stored.title ?? "");
    if (stored.folder) setFolder(stored.folder);
    if (stored.name) {
      setName(stored.name);
      setNameTouched(stored.name !== slugify(stored.title ?? ""));
    } else {
      setName(slugify(stored.title ?? ""));
    }
    setTags(stored.tags ?? []);
    setExpandable(stored.expandable ?? false);
    setGeneration((g) => g + 1);
    setStored(null);
  };

  const create = useCallback(async () => {
    if (saving) return;
    const written = text.trim();
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
          ...(expandable && { meta: { expandable: true } }),
          // Replacing one on purpose: only the version this dialog saw.
          ...(existing && { base_version: existing.version }),
        },
      ]);
      saved.current = true;
      clearDraft(slot);
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
  }, [saving, text, title, name, problem, roomName, key, principal, tags, expandable, existing, slot, revalidate, onDone]);

  // ⌘↵ / ⌘S creates it from anywhere in the dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      if (e.key === "Enter" || e.key.toLowerCase() === "s") {
        e.preventDefault();
        void create();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [create]);

  return (
    <>
      <div className="flex flex-shrink-0 items-start gap-3 border-b border-border px-5 pt-4 pb-3">
        <div className="min-w-0 flex-1">
          <DialogTitle className="text-ui font-semibold text-text">
            New memory in <span className="font-mono">{roomName}</span>
          </DialogTitle>
          <DialogDescription className="mt-1 text-label text-muted-foreground">
            Something the room should keep: a decision, how something works, where things stand. Everyone in the
            room can read it and find it by what it means.
          </DialogDescription>
        </div>
        {/* Beside the dialog's own close button, which sits in the corner. */}
        <div className="mr-7 flex-shrink-0">
          <FullscreenButton on={fullscreen} onToggle={onToggleFullscreen} />
        </div>
      </div>

      {stored && (
        <DraftBanner
          draft={stored}
          note={stored.title?.trim() ? `"${stored.title.trim()}"` : undefined}
          onRestore={restore}
          onDiscard={() => {
            clearDraft(slot);
            setStored(null);
          }}
        />
      )}

      <div
        className={cn(
          "grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-[minmax(0,1fr)_260px]",
          fullscreen && "md:grid-cols-[minmax(0,1fr)_300px] md:overflow-hidden",
        )}
      >
        <div className={cn("flex min-w-0 flex-col gap-3 px-5 py-4", fullscreen && "min-h-0 md:overflow-y-auto")}>
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
                if (mode === "preview") setMode("write");
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
              {/* Sized to what's typed, so the name follows the folder's slash: an
                  invisible copy of the text sets the cell's width. */}
              <span className="inline-grid min-w-0 max-w-[50%] shrink-0 py-2 pl-3">
                <span aria-hidden className="invisible col-start-1 row-start-1 whitespace-pre pr-5">
                  {folder || "folder"}
                </span>
                <input
                  value={folder}
                  onChange={(e) => setFolder(e.target.value)}
                  list="new-memory-folders"
                  aria-label="Folder"
                  placeholder="folder"
                  spellCheck={false}
                  size={1}
                  className="col-start-1 row-start-1 w-full min-w-0 bg-transparent text-muted-foreground outline-none placeholder:text-faint"
                />
              </span>
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
              {nameTouched && title.trim() && name !== slugify(title) && (
                <button
                  type="button"
                  onClick={() => {
                    setName(slugify(title));
                    setNameTouched(false);
                  }}
                  className="mr-1.5 shrink-0 rounded px-1.5 py-0.5 font-sans text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                >
                  Use title
                </button>
              )}
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

          <MemoryBodyEditor
            editorRef={editorRef}
            value={text}
            onChange={setText}
            cursor={cursor}
            mode={mode}
            onModeChange={setMode}
            keys={keys}
            expandableKeys={expandableKeys}
            generation={generation}
            placeholder="Write it down. Markdown works, and [[ links to another memory."
            className={fullscreen ? "min-h-[50vh] flex-1" : undefined}
            bodyClassName={fullscreen ? undefined : "max-h-[340px] min-h-[220px]"}
          />

          <TagInput value={tags} onChange={setTags} suggestions={roomTags} placeholder="Add tag…" ariaLabel="Tags" />
        </div>

        <aside
          className={cn(
            "flex flex-col gap-5 border-t border-border bg-surface/40 px-4 py-4 md:border-l md:border-t-0",
            fullscreen && "min-h-0 md:overflow-y-auto",
          )}
        >
          <section>
            <p className="mb-3 text-micro font-medium text-faint">Where it goes</p>
            <TreePreview roomName={roomName} slice={slice} version={existing?.version ?? null} />
          </section>
          <label className="flex cursor-pointer select-none items-start gap-2">
            <input
              type="checkbox"
              checked={expandable}
              onChange={(e) => setExpandable(e.target.checked)}
              className="mt-0.5 rounded border-border text-accent accent-accent"
            />
            <span className="text-label text-text">
              Expandable
              <span className="block text-micro text-muted-foreground">
                Other memories can embed it whole with <span className="font-mono">![[…]]</span>.
              </span>
            </span>
          </label>
          <DraftLinks text={text} keys={keySet} />
        </aside>
      </div>

      <div className="flex flex-shrink-0 items-center gap-3 border-t border-border px-5 py-2.5">
        {error ? (
          <p role="alert" className="min-w-0 flex-1 truncate text-label text-red">
            {error}
          </p>
        ) : (
          <span className="flex min-w-0 flex-1 items-center gap-3 text-micro text-faint">
            <span className="flex items-center gap-1.5">
              <Kbd size="xs" tone="muted">{mac ? "⌘↵" : "Ctrl+↵"}</Kbd> to save
            </span>
            <span className="hidden items-center gap-1.5 sm:flex">
              <Kbd size="xs" tone="muted">{mac ? "⌘⇧F" : "Ctrl+Shift+F"}</Kbd> {fullscreen ? "leave full screen" : "full screen"}
            </span>
          </span>
        )}
        <Button variant="ghost" size="sm" onClick={discard} disabled={saving}>
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
