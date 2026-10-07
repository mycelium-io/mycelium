// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { FileX } from "lucide-react";
import type { Upload } from "@/lib/api";
import { useRoomUploads } from "@/lib/room-data";
import { formatBytes, kindLabel } from "@/lib/uploads";
import { KIND_ICON } from "@/components/uploads/upload-preview";

/**
 * The files a message links, drawn under it: images as thumbnails, everything
 * else as a card with its name and size. Clicking one opens the preview.
 *
 * The message's own `[[uploads/…]]` chips stay in its prose; this is the same
 * files at a size that shows what they are. A link to an upload that has since
 * been removed reads as removed rather than vanishing.
 */
export function AttachmentStrip({
  roomName,
  keys,
  onOpen,
}: {
  roomName: string;
  keys: string[];
  onOpen: (upload: Upload) => void;
}) {
  const { uploads, loading } = useRoomUploads(roomName);
  if (!keys.length) return null;
  const byKey = new Map(uploads.map((u) => [u.key, u]));

  return (
    <div className="mt-1.5 flex flex-wrap gap-2">
      {keys.map((key) => {
        const upload = byKey.get(key);
        if (!upload) {
          if (loading) return null;
          return (
            <span
              key={key}
              className="inline-flex h-12 items-center gap-2 rounded-lg border border-dashed border-border px-3 text-micro text-faint"
            >
              <FileX className="size-4" /> {key.slice("uploads/".length)} was removed
            </span>
          );
        }
        if (upload.kind === "image") {
          return (
            <button
              key={key}
              type="button"
              onClick={() => onOpen(upload)}
              aria-label={`Preview ${upload.filename}`}
              className="overflow-hidden rounded-lg border border-border bg-surface transition-colors hover:border-border2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset */}
              <img src={upload.url} alt={upload.filename} loading="lazy" className="block h-32 max-w-64 object-cover" />
            </button>
          );
        }
        const Icon = KIND_ICON[upload.kind];
        return (
          <button
            key={key}
            type="button"
            onClick={() => onOpen(upload)}
            aria-label={`Preview ${upload.filename}`}
            className="inline-flex h-12 max-w-72 items-center gap-2.5 rounded-lg border border-border bg-surface px-3 text-left transition-colors hover:border-border2 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <Icon className="size-5 shrink-0 text-muted-foreground" />
            <span className="min-w-0">
              <span className="block truncate text-label text-text">{upload.filename}</span>
              <span className="block text-micro text-faint">
                {kindLabel(upload.kind)} · {formatBytes(upload.size)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
