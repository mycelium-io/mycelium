// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { FileX, ImageOff } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { Upload } from "@/lib/api";
import { useRoomUploads } from "@/lib/room-data";
import { formatBytes, kindLabel, mediaUrl } from "@/lib/uploads";
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
          // The room's file list hasn't arrived yet: hold the space the file
          // will take, guessed from its name, so the message doesn't jump.
          if (loading) {
            return LIKELY_IMAGE.test(key) ? (
              <Skeleton key={key} className="h-32 w-48 rounded-lg" />
            ) : (
              <Skeleton key={key} className="h-12 w-56 rounded-lg" />
            );
          }
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
          return <ImageThumb key={key} upload={upload} onOpen={onOpen} />;
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

/** An upload key that names an image, for sizing its placeholder before the
 *  room's file list says what kind it is. */
const LIKELY_IMAGE = /\.(png|jpe?g|gif|webp|avif)$/i;

/** A thumbnail's height is fixed; its width starts at a placeholder and
 *  settles to the image's own shape once it loads, never past this. */
const THUMB_HEIGHT = 128;
const THUMB_MAX_WIDTH = 256;

/**
 * One image attachment. The hub doesn't record an image's size, so the frame
 * holds a fixed height from the start, with a skeleton in it while the image
 * loads; only the width changes when it arrives, so the message never jumps
 * vertically. An image that fails to load shows its name instead of an empty
 * frame, and still opens the preview.
 */
function ImageThumb({ upload, onOpen }: { upload: Upload; onOpen: (upload: Upload) => void }) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [width, setWidth] = useState<number | null>(null);

  if (state === "failed") {
    return (
      <button
        type="button"
        onClick={() => onOpen(upload)}
        aria-label={`Preview ${upload.filename}`}
        className="inline-flex h-32 w-48 flex-col items-center justify-center gap-2 rounded-lg border border-border bg-surface px-3 text-center transition-colors hover:border-border2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <ImageOff className="size-5 text-muted-foreground" />
        <span className="w-full truncate text-label text-text">{upload.filename}</span>
        <span className="text-micro text-faint">Couldn&apos;t load the image</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onOpen(upload)}
      aria-label={`Preview ${upload.filename}`}
      style={{ height: THUMB_HEIGHT, width: width ?? 192 }}
      className="relative overflow-hidden rounded-lg border border-border bg-surface transition-[border-color,width] duration-200 hover:border-border2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 motion-reduce:transition-none"
    >
      {state === "loading" && <Skeleton className="absolute inset-0 rounded-none" />}
      {/* eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset */}
      <img
        src={mediaUrl(upload.url)}
        alt={upload.filename}
        loading="lazy"
        onLoad={(e) => {
          const img = e.currentTarget;
          if (img.naturalHeight > 0) {
            setWidth(Math.min(THUMB_MAX_WIDTH, Math.max(64, Math.round((img.naturalWidth / img.naturalHeight) * THUMB_HEIGHT))));
          }
          setState("ready");
        }}
        onError={() => setState("failed")}
        className={`block h-full w-full object-cover transition-opacity duration-200 motion-reduce:transition-none ${state === "ready" ? "opacity-100" : "opacity-0"}`}
      />
    </button>
  );
}
