// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Upload } from "@/lib/api";
import { downloadUrl } from "@/lib/uploads";
import { distinctNames, zipStored } from "@/lib/zip";

/**
 * Several uploads saved as one zip, built here from each file's own download
 * (signed, as a single file's is). A message's files are small enough to hold
 * in memory, so this needs no route of the hub's own.
 */

/** What the zip is called: the room, then the time, `checkout-2026-11-14-1603.zip`. */
export function zipName(room: string, at: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}`;
  return `${room}-${stamp}.zip`;
}

/** Fetch each upload and zip them, each under the name it was added with. */
export async function zipUploads(uploads: Upload[]): Promise<Blob> {
  const names = distinctNames(uploads.map((u) => u.filename || u.name));
  const files = await Promise.all(
    uploads.map(async (upload, i) => {
      const res = await fetch(downloadUrl(upload));
      if (!res.ok) throw new Error(`Couldn't fetch ${upload.filename}`);
      return { name: names[i], data: new Uint8Array(await res.arrayBuffer()), modified: new Date(upload.created_at) };
    }),
  );
  return zipStored(files);
}

/** Hand a blob to the browser to save. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Long enough for the browser to have started the save.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
