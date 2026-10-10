// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { MarkdownContent } from "@/components/markdown-content";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Ago } from "@/lib/relative-time";
import { fetchUploadText, type Upload, type UploadKind } from "@/lib/api";
import { downloadUrl, formatBytes, kindLabel, parseDelimited, textViewFor } from "@/lib/uploads";
import { cn } from "@/lib/utils";

const PdfPreview = dynamic(() => import("@/components/uploads/pdf-preview").then((m) => m.PdfPreview), {
  ssr: false,
  loading: () => <Loading what="the PDF" />,
});

export const KIND_ICON: Record<UploadKind, LucideIcon> = {
  image: FileImage,
  pdf: FileText,
  text: FileText,
  audio: FileAudio,
  video: FileVideo,
};

/** Text past this is cut in the preview; the download has all of it. */
const TEXT_PREVIEW_CHARS = 200_000;

function Loading({ what }: { what: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-label text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Loading {what}…
    </div>
  );
}

function TextPreview({ upload, onOpenMemory }: { upload: Upload; onOpenMemory?: (key: string) => void }) {
  const { data, error } = useSWR(["upload-text", upload.url, upload.sha256], () => fetchUploadText(upload));
  const view = textViewFor(upload.filename);
  const text = data && data.length > TEXT_PREVIEW_CHARS ? data.slice(0, TEXT_PREVIEW_CHARS) : data;
  const rows = useMemo(
    () => (text && view === "table" ? parseDelimited(text, upload.filename.toLowerCase().endsWith(".tsv") ? "\t" : ",") : []),
    [text, view, upload.filename],
  );

  if (error) return <p className="py-6 text-label text-muted-foreground">Couldn&apos;t load this file.</p>;
  if (text === undefined) return <Loading what="the file" />;
  const cut = data !== undefined && data.length > TEXT_PREVIEW_CHARS && (
    <p className="mt-2 text-micro text-faint">This preview is cut short. Download the file for all of it.</p>
  );

  if (view === "markdown") {
    return (
      <>
        <MarkdownContent className="contrast text-body leading-relaxed" onLinkClick={onOpenMemory}>
          {text}
        </MarkdownContent>
        {cut}
      </>
    );
  }
  if (view === "table" && rows.length) {
    const [head, ...body] = rows;
    return (
      <>
        <div className="overflow-auto rounded-lg border border-border">
          <table className="w-full border-collapse text-micro">
            <thead className="sticky top-0 bg-surface">
              <tr>
                {head.map((cell, i) => (
                  <th key={i} className="border-b border-border px-2 py-1 text-left font-medium text-text">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r} className="odd:bg-hairline/40">
                  {row.map((cell, c) => (
                    <td key={c} className="px-2 py-1 align-top font-mono text-text">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(rows.length >= 500 || cut) && (
          <p className="mt-2 text-micro text-faint">Showing the first {rows.length} rows. Download the file for all of it.</p>
        )}
      </>
    );
  }
  return (
    <>
      <pre className="overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-micro leading-relaxed text-text whitespace-pre">
        {text}
      </pre>
      {cut}
    </>
  );
}

/** The file itself, drawn the way its kind is read: an image, a PDF's pages,
 *  text (rendered Markdown, a table, or source), or a player. */
export function UploadPreview({
  upload,
  onOpenMemory,
  className,
}: {
  upload: Upload;
  onOpenMemory?: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={className}>
      {upload.kind === "image" && (
        // eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset
        <img
          src={upload.url}
          alt={upload.filename}
          className="mx-auto block max-h-[70vh] max-w-full rounded-md object-contain"
        />
      )}
      {upload.kind === "pdf" && <PdfPreview url={upload.url} />}
      {upload.kind === "text" && <TextPreview upload={upload} onOpenMemory={onOpenMemory} />}
      {upload.kind === "audio" && <audio controls preload="metadata" src={upload.url} className="w-full" />}
      {upload.kind === "video" && (
        <video controls preload="metadata" src={upload.url} className="mx-auto block max-h-[70vh] max-w-full rounded-md" />
      )}
    </div>
  );
}

/** What it is, who added it and when, on one line. */
export function UploadFacts({ upload, className }: { upload: Upload; className?: string }) {
  return (
    <span className={cn("tabular text-micro text-muted-foreground", className)}>
      {kindLabel(upload.kind)} · {formatBytes(upload.size)} · {upload.created_by} · <Ago at={upload.created_at} />
    </span>
  );
}

export function DownloadButton({ upload, size = "sm" }: { upload: Upload; size?: "sm" | "xs" }) {
  return (
    <a href={downloadUrl(upload)} download={upload.filename} className={buttonVariants({ variant: "outline", size })}>
      <Download className="size-3.5" /> Download
    </a>
  );
}

/** The one `step` away from `current` in `set`, wrapping at the ends; `null`
 *  when there is nowhere to go (no set, a set of one, or `current` not in it). */
export function stepThrough(set: Upload[], current: Upload | null, step: 1 | -1): Upload | null {
  if (!current || set.length < 2) return null;
  const at = set.findIndex((u) => u.key === current.key);
  if (at < 0) return null;
  return set[(at + step + set.length) % set.length];
}

/** The set as a strip of small previews under the file: images as thumbnails,
 *  anything else as its kind's icon. The one shown is lit and kept in view;
 *  clicking another shows it. */
function Filmstrip({ set, current, onShow }: { set: Upload[]; current: Upload; onShow: (upload: Upload) => void }) {
  const activeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [current.key]);

  return (
    <div className="flex min-w-0 gap-1.5 overflow-x-auto px-1 py-1">
      {set.map((u) => {
        const active = u.key === current.key;
        const Icon = KIND_ICON[u.kind];
        return (
          <button
            key={u.key}
            ref={active ? activeRef : undefined}
            type="button"
            onClick={() => onShow(u)}
            aria-label={`Show ${u.filename}`}
            aria-current={active || undefined}
            title={u.filename}
            className={cn(
              "flex size-12 flex-shrink-0 items-center justify-center overflow-hidden rounded-md border bg-surface transition",
              active
                ? "border-accent ring-1 ring-accent"
                : "border-border opacity-60 hover:opacity-100 focus-visible:opacity-100",
            )}
          >
            {u.kind === "image" ? (
              // eslint-disable-next-line @next/next/no-img-element -- the hub's bytes, not a static asset
              <img src={u.url} alt="" loading="lazy" className="size-full object-cover" />
            ) : (
              <Icon className="size-5 text-muted-foreground" />
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The preview window: the file at a readable size, with its download. Given
 *  the `set` it was opened from (a message's attachments), it steps through
 *  them with its arrows or ← and →, wrapping at the ends, and shows the whole
 *  set as a strip along the bottom. */
export function UploadPreviewDialog({
  upload,
  onClose,
  onOpenMemory,
  set = [],
  onShow,
}: {
  upload: Upload | null;
  onClose: () => void;
  onOpenMemory?: (key: string) => void;
  /** The files it was opened among, in order. */
  set?: Upload[];
  /** Show another file of `set`; without it the window can't step. */
  onShow?: (upload: Upload) => void;
}) {
  // Keep the last file drawn while the window animates closed.
  const [shown, setShown] = useState(upload);
  if (upload && upload !== shown) setShown(upload);

  const stepping = Boolean(onShow) && set.length > 1;
  const at = shown ? set.findIndex((u) => u.key === shown.key) : -1;
  const go = (step: 1 | -1) => {
    const next = stepThrough(set, shown, step);
    if (next && onShow) onShow(next);
  };

  return (
    <Dialog open={upload !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-4xl"
        onKeyDown={(e) => {
          // Not while typing, or while a player has focus and wants its own keys.
          const tag = (e.target as HTMLElement).tagName;
          if (!stepping || tag === "INPUT" || tag === "TEXTAREA" || tag === "AUDIO" || tag === "VIDEO") return;
          if (e.key === "ArrowRight") {
            e.preventDefault();
            go(1);
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            go(-1);
          }
        }}
      >
        {shown && (
          <>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border py-2.5 pr-12 pl-4">
              <div className="min-w-0 flex-1">
                <DialogTitle className="truncate text-label text-text">{shown.filename}</DialogTitle>
                <DialogDescription>
                  <UploadFacts upload={shown} />
                </DialogDescription>
              </div>
              {onOpenMemory && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onClose();
                    onOpenMemory(shown.key);
                  }}
                >
                  Open in memory
                </Button>
              )}
              <DownloadButton upload={shown} />
            </div>
            <div className="min-h-0 overflow-auto p-4">
              <UploadPreview upload={shown} onOpenMemory={onOpenMemory} />
            </div>
            {stepping && onShow && (
              <div className="flex items-center gap-2 border-t border-border px-3 py-1.5">
                {/* Balances the count, so the strip sits in the middle. */}
                <span aria-hidden className="w-12 flex-shrink-0" />
                <div className="flex min-w-0 flex-1 items-center justify-center gap-1">
                  <IconButton label="Previous file" side="top" onClick={() => go(-1)}>
                    <ChevronLeft />
                  </IconButton>
                  <Filmstrip set={set} current={shown} onShow={onShow} />
                  <IconButton label="Next file" side="top" onClick={() => go(1)}>
                    <ChevronRight />
                  </IconButton>
                </div>
                <span className="w-12 flex-shrink-0 text-right tabular text-micro text-muted-foreground">
                  {at + 1} of {set.length}
                </span>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
