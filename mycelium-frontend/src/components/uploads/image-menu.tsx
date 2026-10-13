// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Copy, Download, Image as ImageIcon, Link2 } from "lucide-react";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import type { Upload } from "@/lib/api";
import { absoluteUrl, copyImage, copyText } from "@/lib/clipboard";
import { isMacPlatform } from "@/lib/keymap";
import { downloadUrl } from "@/lib/uploads";
import { cn } from "@/lib/utils";

/** How long "Copied" stays up. */
const NOTICE_MS = 1800;

export interface CopyNoticeState {
  text: string;
  failed: boolean;
}

/**
 * Copying a file's image or link, and what to say about it afterwards: a short
 * "Copied", or plainly why it didn't.
 */
export function useFileCopy() {
  const [notice, setNotice] = useState<CopyNoticeState | null>(null);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), notice.failed ? NOTICE_MS * 2 : NOTICE_MS);
    return () => clearTimeout(t);
  }, [notice]);

  const image = useCallback((upload: Upload) => {
    copyImage(upload.url).then(
      () => setNotice({ text: "Image copied", failed: false }),
      (err: unknown) =>
        setNotice({ text: err instanceof Error && err.message ? err.message : "Couldn't copy the image.", failed: true }),
    );
  }, []);
  const link = useCallback((upload: Upload) => {
    void copyText(absoluteUrl(upload.url)).then(() => setNotice({ text: "Link copied", failed: false }));
  }, []);
  return { notice, image, link };
}

/** Save a file the way its Download button does. */
export function downloadFile(upload: Upload): void {
  const a = document.createElement("a");
  a.href = downloadUrl(upload);
  a.download = upload.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * The right-click menu on a file: Copy image (an image only), Copy link and
 * Download, in the app's own menu, so it looks the same everywhere and is
 * there in the desktop app, whose webview has no browser menu of its own.
 * The child is rendered in place.
 */
export function FileMenu({
  upload,
  copy,
  children,
}: {
  upload: Upload;
  copy: ReturnType<typeof useFileCopy>;
  children: ReactElement;
}) {
  return (
    <ContextMenu>
      <ContextMenuTrigger>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {upload.kind === "image" && (
          <ContextMenuItem icon={ImageIcon} keys={isMacPlatform() ? "⌘C" : "Ctrl+C"} onClick={() => copy.image(upload)}>
            Copy image
          </ContextMenuItem>
        )}
        <ContextMenuItem icon={Link2} onClick={() => copy.link(upload)}>
          Copy link
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem icon={Download} onClick={() => downloadFile(upload)}>
          Download
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** What a copy said, as a small pill; place it where the file is. */
export function CopyNotice({ notice, className }: { notice: CopyNoticeState | null; className?: string }) {
  return (
    <span role="status" aria-live="polite" className={cn("pointer-events-none", className)}>
      {notice && (
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-micro shadow-md",
            notice.failed ? "border-red/40 bg-popover text-red" : "border-border bg-popover text-text",
          )}
        >
          {!notice.failed && <Copy className="size-3" />}
          {notice.text}
        </span>
      )}
    </span>
  );
}
