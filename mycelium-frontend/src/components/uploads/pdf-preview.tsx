// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

/** Pages past this aren't drawn; the download has the rest. */
const MAX_PAGES = 30;

/**
 * A PDF drawn page by page onto canvases with pdf.js.
 *
 * The browser's own viewer won't open a document the hub serves sandboxed, and
 * shouldn't: drawing it here keeps the file inert. pdf.js renders the pages and
 * never runs the document's scripts or forms. Loaded on first use, so the app
 * carries none of it until someone opens a PDF.
 */
export function PdfPreview({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ pages: number; shown: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    let destroy: (() => void) | undefined;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const task = pdfjs.getDocument({ url, enableXfa: false });
        destroy = () => void task.destroy();
        const doc = await task.promise;
        if (cancelled) return;
        const shown = Math.min(doc.numPages, MAX_PAGES);
        setState({ pages: doc.numPages, shown });
        const width = el.clientWidth || 720;
        const ratio = window.devicePixelRatio || 1;
        for (let n = 1; n <= shown && !cancelled; n++) {
          const page = await doc.getPage(n);
          const base = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: (width / base.width) * ratio });
          const canvas = document.createElement("canvas");
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.style.width = "100%";
          canvas.className = "block rounded-sm bg-white shadow-sm ring-1 ring-hairline";
          canvas.setAttribute("aria-label", `Page ${n}`);
          el.appendChild(canvas);
          await page.render({ canvas, viewport }).promise;
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "This PDF couldn't be drawn");
      }
    })();
    return () => {
      cancelled = true;
      destroy?.();
      el.replaceChildren();
    };
  }, [url]);

  return (
    <div className="space-y-3">
      {!state && !error && (
        <div className="flex items-center gap-2 py-10 text-label text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Drawing the PDF…
        </div>
      )}
      {error && <p className="py-6 text-label text-muted-foreground">Couldn&apos;t show this PDF: {error}</p>}
      <div ref={host} className="space-y-3" />
      {state && state.pages > state.shown && (
        <p className="text-micro text-faint">
          Showing the first {state.shown} of {state.pages} pages. Download it for the rest.
        </p>
      )}
    </div>
  );
}
