// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, X } from "lucide-react";
import { uploadFile, type Upload } from "@/lib/api";
import { useRoomUploads } from "@/lib/room-data";
import { extensionOf, formatBytes, refusalFor, uploadLink } from "@/lib/uploads";
import { KIND_ICON } from "@/components/uploads/upload-preview";
import { cn } from "@/lib/utils";

/** A file on its way into the room from the composer. */
export interface Pending {
  id: string;
  file: File;
  /** A local thumbnail while it uploads, for an image. */
  thumb: string | null;
  progress: number;
  status: "uploading" | "done" | "failed";
  upload?: Upload;
  error?: string;
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp"]);

/**
 * The files a message will carry. Each starts uploading the moment it's added,
 * so by the time the text is written they are usually already in the room; the
 * message then links each as `[[uploads/<name>]]`. A file the hub won't take is
 * said on its chip before anything is sent, and the rest go on without it.
 */
export function usePendingUploads(roomName: string, handle: string) {
  const [items, setItems] = useState<Pending[]>([]);
  const { accepted, max_bytes, refresh } = useRoomUploads(roomName);
  const controllers = useRef(new Map<string, AbortController>());

  const patch = useCallback((id: string, change: Partial<Pending>) => {
    setItems((all) => all.map((p) => (p.id === id ? { ...p, ...change } : p)));
  }, []);

  const drop = useCallback((p: Pending) => {
    controllers.current.get(p.id)?.abort();
    controllers.current.delete(p.id);
    if (p.thumb) URL.revokeObjectURL(p.thumb);
  }, []);

  const add = useCallback(
    (files: Iterable<File>) => {
      const added: Pending[] = [];
      for (const file of files) {
        const refused = refusalFor(file, accepted, max_bytes);
        const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const thumb = !refused && IMAGE_EXT.has(extensionOf(file.name)) ? URL.createObjectURL(file) : null;
        const item: Pending = { id, file, thumb, progress: 0, status: refused ? "failed" : "uploading", error: refused ?? undefined };
        added.push(item);
        if (refused) continue;
        const controller = new AbortController();
        controllers.current.set(id, controller);
        uploadFile(roomName, file, handle, {
          signal: controller.signal,
          onProgress: (progress) => patch(id, { progress }),
        })
          .then((upload) => {
            patch(id, { status: "done", progress: 1, upload });
            refresh();
          })
          .catch((err: unknown) => {
            if (err instanceof DOMException && err.name === "AbortError") return;
            patch(id, { status: "failed", error: err instanceof Error ? err.message : String(err) });
          })
          .finally(() => controllers.current.delete(id));
      }
      if (added.length) setItems((all) => [...all, ...added]);
    },
    [accepted, max_bytes, roomName, handle, patch, refresh],
  );

  const remove = useCallback(
    (id: string) => {
      setItems((all) => {
        const gone = all.find((p) => p.id === id);
        if (gone) drop(gone);
        return all.filter((p) => p.id !== id);
      });
    },
    [drop],
  );

  const clear = useCallback(() => {
    setItems((all) => {
      all.forEach(drop);
      return [];
    });
  }, [drop]);

  // Files belong to the room they were added in.
  useEffect(() => clear, [roomName, clear]);

  const busy = items.some((p) => p.status === "uploading");
  const links = useMemo(
    () => items.flatMap((p) => (p.status === "done" && p.upload ? [uploadLink(p.upload)] : [])),
    [items],
  );
  return { items, add, remove, clear, busy, links, accepted };
}

/** The chips over the composer's text: a thumbnail or icon, the name, a bar
 *  while it uploads, and the hub's reason when it was refused. */
export function PendingAttachments({ items, onRemove }: { items: Pending[]; onRemove: (id: string) => void }) {
  if (!items.length) return null;
  return (
    <ul aria-label="Attached files" className="flex flex-wrap gap-2 px-2.5 pt-2.5">
      {items.map((p) => {
        const Icon = p.upload ? KIND_ICON[p.upload.kind] : KIND_ICON.text;
        const failed = p.status === "failed";
        return (
          <li
            key={p.id}
            className={cn(
              "relative flex h-12 max-w-64 items-center gap-2 overflow-hidden rounded-lg border bg-bg pr-7 pl-1.5",
              failed ? "border-red/40" : "border-border",
            )}
          >
            {p.thumb ? (
              // eslint-disable-next-line @next/next/no-img-element -- a local object URL
              <img src={p.thumb} alt="" className="size-9 shrink-0 rounded object-cover" />
            ) : (
              <span className="grid size-9 shrink-0 place-items-center rounded bg-surface">
                {failed ? <AlertCircle className="size-4 text-red" /> : <Icon className="size-4 text-muted-foreground" />}
              </span>
            )}
            <span className="min-w-0">
              <span className="block truncate text-label text-text">{p.file.name}</span>
              <span className={cn("block truncate text-micro", failed ? "text-red" : "text-faint")} title={p.error}>
                {failed ? p.error : p.status === "uploading" ? `Uploading ${Math.round(p.progress * 100)}%` : formatBytes(p.upload?.size ?? p.file.size)}
              </span>
            </span>
            <button
              type="button"
              aria-label={`Remove ${p.file.name}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onRemove(p.id)}
              className="absolute top-1 right-1 grid size-5 place-items-center rounded text-muted-foreground hover:bg-hairline hover:text-text"
            >
              <X className="size-3" />
            </button>
            {p.status === "uploading" && (
              <span
                aria-hidden
                className="absolute inset-x-0 bottom-0 h-0.5 bg-accent transition-[width] duration-150"
                style={{ width: `${Math.max(4, p.progress * 100)}%` }}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
