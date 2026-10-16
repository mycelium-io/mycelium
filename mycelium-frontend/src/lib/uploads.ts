// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Upload, UploadKind } from "@/lib/api";

/** The memory namespace uploads live in; `[[uploads/<name>]]` links one. */
export const UPLOADS_PREFIX = "uploads/";

export function isUploadKey(key: string): boolean {
  return key.startsWith(UPLOADS_PREFIX);
}

/** The `[[uploads/…]]` links in a message, in order, each once. A code span
 *  or block is prose about the syntax, so links inside one don't count. */
export function uploadKeysIn(text: string): string[] {
  const prose = text.replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");
  const keys: string[] = [];
  for (const match of prose.matchAll(/(?<!!)\[\[(uploads\/[^\]|#\n]+)(?:[|#][^\]\n]*)?\]\]/g)) {
    const key = match[1].trim();
    if (!keys.includes(key)) keys.push(key);
  }
  return keys;
}

/** A message's prose without the trailing line of upload links the composer
 *  adds, for drawing above the files themselves. The text sent keeps them (an
 *  agent reads the links); a link written mid-sentence is left where it is. */
export function withoutTrailingUploadLinks(text: string): string {
  return text.replace(/(?:^|\n)(?:[ \t]*\[\[uploads\/[^\]\n]+\]\][ \t]*)+\s*$/, "").trimEnd();
}

/** The link to put in a message for an upload. */
export function uploadLink(upload: Pick<Upload, "key">): string {
  return `[[${upload.key}]]`;
}

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 || (dot === 0 && filename.length > 1) ? filename.slice(dot + 1).toLowerCase() : "";
}

/** Why the hub would refuse this file, said before sending it, or null when
 *  it should take it. The hub checks again: this only saves a round trip. */
export function refusalFor(
  file: Pick<File, "name" | "size">,
  accepted: readonly string[],
  maxBytes: number,
): string | null {
  const ext = extensionOf(file.name);
  if (accepted.length && !accepted.includes(ext)) {
    return ext ? `.${ext} files can't be previewed, so they can't be uploaded` : "Files without an extension can't be uploaded";
  }
  if (maxBytes && file.size > maxBytes) return `Larger than ${formatBytes(maxBytes)}`;
  if (file.size === 0) return "This file is empty";
  return null;
}

/** The `accept` attribute for a file picker, from the hub's list. */
export function acceptAttribute(accepted: readonly string[]): string | undefined {
  return accepted.length ? accepted.map((ext) => `.${ext}`).join(",") : undefined;
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** How a text upload is drawn: rendered Markdown, a table, or source. */
export type TextView = "markdown" | "table" | "source";

export function textViewFor(filename: string): TextView {
  const ext = extensionOf(filename);
  if (ext === "md" || ext === "markdown") return "markdown";
  if (ext === "csv" || ext === "tsv") return "table";
  return "source";
}

/** A CSV or TSV file as rows, quotes honoured. Enough for a preview; capped so
 *  a large file can't stall the page. */
export function parseDelimited(text: string, delimiter: string, maxRows = 500): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
      continue;
    }
    if (ch === '"' && cell === "") quoted = true;
    else if (ch === delimiter) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (rows.length >= maxRows) return rows;
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export function kindLabel(kind: UploadKind): string {
  return { image: "Image", pdf: "PDF", text: "Text", audio: "Audio", video: "Video" }[kind];
}

export function downloadUrl(upload: Pick<Upload, "url">): string {
  return `${upload.url}?download=1`;
}
