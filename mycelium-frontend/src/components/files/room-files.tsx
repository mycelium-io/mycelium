// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { Download, FileUp, Loader2, Search, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select } from "@/components/ui/select";
import { KIND_ICON, UploadPreviewDialog } from "@/components/uploads/upload-preview";
import { CopyNotice, FileMenu, downloadFile, useFileCopy } from "@/components/uploads/image-menu";
import { deleteUpload, type Upload } from "@/lib/api";
import { useRoomUploads } from "@/lib/room-data";
import {
  NO_FILTER,
  filterFiles,
  groupByDay,
  isFiltered,
  originLabel,
  posterOf,
  postersIn,
  tasksIn,
  type FileFilter,
  type Where,
} from "@/lib/room-files";
import { formatBytes } from "@/lib/uploads";
import { cn } from "@/lib/utils";

interface Props {
  roomName: string;
  onOpenThread: (episode: string) => void;
  onOpenMessage: (id: string) => void;
  onOpenMemory: (key: string) => void;
}

/** `Where` as a select's value, and back. */
function whereValue(where: Where): string {
  return typeof where === "string" ? where : `task:${where.task}`;
}
function whereFrom(value: string): Where {
  if (value.startsWith("task:")) return { task: value.slice(5) };
  return value as Where;
}

/**
 * A room's uploads as a gallery: thumbnails newest first, grouped by day, each
 * saying who posted it and where, with a link back to that message. Clicking a
 * file opens the preview window, whose arrows step through the gallery as it's
 * filtered. Several can be selected to download or delete together.
 */
export function RoomFiles({ roomName, onOpenThread, onOpenMessage, onOpenMemory }: Props) {
  const { uploads, loading, refresh } = useRoomUploads(roomName);
  const [filter, setFilter] = useState<FileFilter>(NO_FILTER);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [preview, setPreview] = useState<Upload | null>(null);
  const [deleting, setDeleting] = useState(false);
  const copy = useFileCopy();

  const shown = useMemo(() => filterFiles(uploads, filter), [uploads, filter]);
  const groups = useMemo(() => groupByDay(shown), [shown]);
  const posters = useMemo(() => postersIn(uploads), [uploads]);
  const tasks = useMemo(() => tasksIn(uploads), [uploads]);
  const chosen = uploads.filter((u) => selected.has(u.key));

  const toggle = (key: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const downloadChosen = () => {
    // One link per file; the browser may ask once whether this page can save
    // several files.
    for (const u of chosen) downloadFile(u);
  };

  const openOrigin = (u: Upload) => {
    const o = u.posted_in;
    if (!o) onOpenMemory(u.key);
    else if (o.episode) onOpenThread(o.episode);
    else onOpenMessage(o.message_id);
  };

  if (!loading && uploads.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-bg px-6 text-center">
        <FileUp className="size-6 text-faint" strokeWidth={1.6} />
        <p className="text-body text-text">No files in this room yet</p>
        <p className="max-w-sm text-label text-muted-foreground">
          Drop a file into any message box, or add one from a terminal with{" "}
          <code className="font-mono text-micro">mycelium file upload &lt;path&gt;</code>. Each one shows here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <label className="flex h-7 min-w-40 flex-1 items-center gap-1.5 rounded-md border border-border px-2 text-label focus-within:border-accent">
          <Search className="size-3.5 shrink-0 text-faint" />
          <input
            type="search"
            aria-label="Search file names"
            placeholder="Search file names"
            value={filter.query}
            onChange={(e) => setFilter({ ...filter, query: e.target.value })}
            className="min-w-0 flex-1 bg-transparent text-text outline-none placeholder:text-faint"
          />
        </label>
        <Select
          aria-label="Kind of file"
          value={filter.kind}
          onChange={(e) => setFilter({ ...filter, kind: e.target.value as FileFilter["kind"] })}
          size="xs"
        >
          <option value="all">All files</option>
          <option value="images">Images</option>
          <option value="other">Other files</option>
        </Select>
        <Select
          aria-label="Posted by"
          value={filter.by ?? ""}
          onChange={(e) => setFilter({ ...filter, by: e.target.value || null })}
          size="xs"
        >
          <option value="">Anyone</option>
          {posters.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Posted in"
          value={whereValue(filter.where)}
          onChange={(e) => setFilter({ ...filter, where: whereFrom(e.target.value) })}
          size="xs"
          className="max-w-56"
        >
          <option value="any">Anywhere</option>
          <option value="channel">The channel</option>
          {tasks.map((t) => (
            <option key={t.key} value={`task:${t.key}`}>
              {t.title}
            </option>
          ))}
          <option value="memory">Saved to memory</option>
        </Select>
        <CopyNotice notice={copy.notice} className="ml-auto" />
        <span className={cn("tabular text-micro text-muted-foreground", !copy.notice && "ml-auto")}>
          {shown.length === uploads.length ? `${uploads.length} files` : `${shown.length} of ${uploads.length}`}
        </span>
      </div>

      {selected.size > 0 && (
        <div role="toolbar" aria-label="Selected files" className="flex items-center gap-2 border-b border-border bg-surface px-3 py-1.5">
          <span className="text-label text-text">{selected.size} selected</span>
          <Button variant="outline" size="xs" onClick={downloadChosen}>
            <Download className="size-3.5" /> Download
          </Button>
          <Button variant="outline" size="xs" onClick={() => setDeleting(true)}>
            <Trash2 className="size-3.5" /> Delete
          </Button>
          <Button variant="ghost" size="xs" className="ml-auto" onClick={() => setSelected(new Set())}>
            <X className="size-3.5" /> Clear
          </Button>
        </div>
      )}

      <ScrollArea className="min-h-0 flex-1">
        {shown.length === 0 && isFiltered(filter) ? (
          <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
            <p className="text-label text-muted-foreground">No files match these filters.</p>
            <Button variant="ghost" size="xs" onClick={() => setFilter(NO_FILTER)}>
              Clear the filters
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-5 px-3 py-3">
            {groups.map((g) => (
              <section key={g.day} aria-label={g.label}>
                <h3 className="mb-2 text-micro font-medium text-muted-foreground">{g.label}</h3>
                <ul className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3">
                  {g.files.map((u) => (
                    <FileCard
                      key={u.key}
                      upload={u}
                      selected={selected.has(u.key)}
                      selecting={selected.size > 0}
                      onSelect={(on) => toggle(u.key, on)}
                      onOpen={() => setPreview(u)}
                      onOrigin={() => openOrigin(u)}
                      copy={copy}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </ScrollArea>

      <UploadPreviewDialog
        upload={preview}
        onClose={() => setPreview(null)}
        onOpenMemory={onOpenMemory}
        set={shown}
        onShow={setPreview}
      />
      <DeleteFilesDialog
        roomName={roomName}
        files={deleting ? chosen : []}
        onClose={() => setDeleting(false)}
        onDeleted={() => {
          setSelected(new Set());
          refresh();
        }}
      />
    </div>
  );
}

function FileCard({
  upload,
  selected,
  selecting,
  onSelect,
  onOpen,
  onOrigin,
  copy,
}: {
  upload: Upload;
  selected: boolean;
  /** Something is selected, so every card shows its checkbox. */
  selecting: boolean;
  onSelect: (on: boolean) => void;
  onOpen: () => void;
  onOrigin: () => void;
  copy: ReturnType<typeof useFileCopy>;
}) {
  const Icon = KIND_ICON[upload.kind];
  const time = new Date(upload.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return (
    // A right-click anywhere on the card copies or saves the file.
    <FileMenu upload={upload} copy={copy}>
      <li
        className={cn(
          // A card off screen skips layout and paint. Without it, the desktop
          // app's engine (WebKit) relaid and repainted every card in a room's
          // gallery on each frame of anything animating on the page, a working
          // agent's avatar glow among them: seconds per frame at a few hundred
          // files. `auto` keeps each card's last drawn size once it has one.
          "[content-visibility:auto] [contain-intrinsic-size:auto_220px]",
          "group relative flex flex-col overflow-hidden rounded-lg border bg-surface transition-colors",
          selected ? "border-accent ring-1 ring-accent" : "border-border hover:border-border2",
        )}
      >
        <button
          type="button"
          onClick={onOpen}
          aria-label={`Preview ${upload.filename}`}
          className="flex aspect-[4/3] items-center justify-center overflow-hidden bg-hairline/40 outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          {upload.kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset
            <img src={upload.thumb_url || upload.url} alt="" loading="lazy" draggable={false} className="size-full object-cover" />
          ) : (
            <span className="flex flex-col items-center gap-1.5 px-2 text-center">
              <Icon className="size-7 text-muted-foreground" strokeWidth={1.5} />
              <span className="text-micro uppercase tracking-wide text-faint">{upload.filename.split(".").pop()}</span>
            </span>
          )}
        </button>
        <span
          className={cn(
            "absolute top-1.5 left-1.5 rounded bg-bg/80 p-0.5 transition-opacity",
            selected || selecting ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100",
          )}
        >
          <Checkbox checked={selected} onCheckedChange={(on) => onSelect(Boolean(on))} aria-label={`Select ${upload.filename}`} />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5 px-2 py-1.5">
          <span className="truncate text-label text-text" title={upload.filename}>
            {upload.filename}
          </span>
          <span className="truncate tabular text-micro text-muted-foreground">
            {posterOf(upload)} · {time} · {formatBytes(upload.size)}
          </span>
          <button
            type="button"
            onClick={onOrigin}
            title={upload.posted_in ? "Open the message it was posted with" : "Open it in memory"}
            className="truncate text-left text-micro text-accent hover:underline"
          >
            {originLabel(upload)}
          </button>
        </div>
      </li>
    </FileMenu>
  );
}

/** Asks before files are deleted, naming how many, since it can't be undone here. */
function DeleteFilesDialog({
  roomName,
  files,
  onClose,
  onDeleted,
}: {
  roomName: string;
  files: Upload[];
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const n = files.length;
  const what = n === 1 ? "1 file" : `${n} files`;
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      for (const u of files) await deleteUpload(roomName, u.name);
      onDeleted();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete them");
      onDeleted();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={n > 0} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete {what}?</DialogTitle>
          <DialogDescription>
            {n === 1 ? "It's" : "They're"} removed for everyone in <span className="font-mono">{roomName}</span>. A message
            that links {n === 1 ? "it" : "one"} says it was removed.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-label text-red">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => void remove()} disabled={busy}>
            {busy && <Loader2 className="size-3 animate-spin" />}
            Delete {what}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
