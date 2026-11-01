// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The Files tab's reading of a room's uploads: which ones a filter leaves, in
// what order, grouped by the day they were added, and where each was posted.
// The facts come from the hub's upload records (`posted_in` is the message an
// upload was posted with); nothing here guesses at what a file is about.

import type { Upload } from "@/lib/api";

/** Where a file was posted: a task by its row key, the channel, or nowhere
 *  (saved straight to memory, or its message is gone). */
export type Where = "any" | "channel" | "memory" | { task: string };

export interface FileFilter {
  kind: "all" | "images" | "other";
  /** Who posted it, by handle; null for anyone. */
  by: string | null;
  where: Where;
  /** Words in the file name, matched without case. */
  query: string;
}

export const NO_FILTER: FileFilter = { kind: "all", by: null, where: "any", query: "" };

export function isFiltered(f: FileFilter): boolean {
  return f.kind !== "all" || f.by !== null || f.where !== "any" || f.query.trim() !== "";
}

/** Who posted a file: whoever added it. Not the sender of the message it was
 *  posted with, which can be a teammate sharing someone else's upload. */
export function posterOf(u: Upload): string {
  return u.created_by;
}

function whereMatches(u: Upload, where: Where): boolean {
  if (where === "any") return true;
  if (where === "memory") return !u.posted_in;
  if (where === "channel") return Boolean(u.posted_in) && !u.posted_in?.episode;
  return u.posted_in?.task === where.task;
}

/** The files `f` leaves, newest first. */
export function filterFiles(files: Upload[], f: FileFilter): Upload[] {
  const words = f.query.toLowerCase().split(/\s+/).filter(Boolean);
  return [...files]
    .filter((u) => f.kind === "all" || (f.kind === "images") === (u.kind === "image"))
    .filter((u) => f.by === null || posterOf(u) === f.by)
    .filter((u) => whereMatches(u, f.where))
    .filter((u) => {
      const name = u.filename.toLowerCase();
      return words.every((w) => name.includes(w));
    })
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** Everyone who posted a file, for the "From" filter, by name. */
export function postersIn(files: Upload[]): string[] {
  return [...new Set(files.map(posterOf))].sort((a, b) => a.localeCompare(b));
}

/** Every task a file was posted in, for the "Posted in" filter, by title. */
export function tasksIn(files: Upload[]): { key: string; title: string }[] {
  const seen = new Map<string, string>();
  for (const u of files) {
    const task = u.posted_in?.task;
    if (task && !seen.has(task)) seen.set(task, u.posted_in?.task_title || task);
  }
  return [...seen].map(([key, title]) => ({ key, title })).sort((a, b) => a.title.localeCompare(b.title));
}

export interface DayGroup {
  /** The local day, `YYYY-MM-DD`. */
  day: string;
  label: string;
  files: Upload[];
}

function localDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** What a day's heading says: Today, Yesterday, or the date (with its year
 *  when it isn't this one). */
export function dayLabel(day: string, now: Date = new Date()): string {
  if (day === localDay(now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (day === localDay(yesterday)) return "Yesterday";
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    ...(y === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** `files` (already in order) split by the local day each was added. */
export function groupByDay(files: Upload[], now: Date = new Date()): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const u of files) {
    const day = localDay(new Date(u.created_at));
    const last = groups[groups.length - 1];
    if (last?.day === day) last.files.push(u);
    else groups.push({ day, label: dayLabel(day, now), files: [u] });
  }
  return groups;
}

/** Where a file was posted, in words, for its card. */
export function originLabel(u: Upload): string {
  const o = u.posted_in;
  if (!o) return "Saved to memory";
  if (!o.episode) return "In the channel";
  return `In ${o.task_title || "a thread"}`;
}
