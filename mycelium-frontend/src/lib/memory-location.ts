// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Where a new memory goes: its key from a folder and a name, the folders a room
 * already has, and the slice of the tree it lands in. Pure functions, so the
 * dialog that writes a memory and its tests read the same rules.
 */

/** Folders every room has, offered even before anything is written in them. */
export const STANDARD_FOLDERS = ["context", "decisions", "procedures", "status", "skills"] as const;

/** Folders whose memories are rows on the board: writing one files work. */
export const BOARD_FOLDERS = new Set(["work", "decisions", "status", "failed"]);

/** A title as a key segment: `Refund policy for double charges` → `refund-policy-for-double-charges`. */
export function slugify(title: string): string {
  return title
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/g, "");
}

/** A folder path cleaned up the way a person means it: no stray or doubled slashes. */
export function cleanFolder(folder: string): string {
  return folder
    .trim()
    .toLowerCase()
    .split("/")
    .map((s) => s.trim())
    .filter(Boolean)
    .join("/");
}

/** The key a folder and a name make. */
export function joinKey(folder: string, name: string): string {
  const f = cleanFolder(folder);
  const n = name.trim().toLowerCase();
  return f ? `${f}/${n}` : n;
}

const SEGMENT = /^[a-z0-9][a-z0-9._-]*$/;

/** Why a key can't be used, or null when it can. */
export function keyProblem(key: string): string | null {
  if (!key) return "Give it a name.";
  if (key.length > 512) return "That's too long for a key.";
  const segments = key.split("/");
  if (segments.some((s) => s === "" || s === "." || s === "..")) return "Folders can't be empty.";
  if (!segments.every((s) => SEGMENT.test(s))) {
    return "Use lowercase letters, digits, - and _, with / between folders.";
  }
  return null;
}

/** Every folder a set of keys implies, with how many memories sit under each. */
export function folderCounts(keys: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const key of keys) {
    const parts = key.split("/");
    for (let i = 1; i < parts.length; i++) {
      const folder = parts.slice(0, i).join("/");
      counts.set(folder, (counts.get(folder) ?? 0) + 1);
    }
  }
  return counts;
}

/** The top-level folders to offer as quick picks: the room's own, busiest first, then the standard ones. */
export function folderChoices(keys: string[]): string[] {
  const counts = folderCounts(keys);
  const top = [...counts.entries()]
    .filter(([f]) => !f.includes("/") && f !== "agents" && f !== "log")
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([f]) => f);
  for (const f of STANDARD_FOLDERS) if (!top.includes(f)) top.push(f);
  return top;
}

export interface TreeSlice {
  /** The folders from the room's root down to the new memory's folder. */
  path: string[];
  /** Which of those folders already exist. */
  existing: boolean[];
  /** What already sits beside the new memory: its folder's subfolders and memories. */
  folders: string[];
  files: string[];
  /** How many more of each there are than are listed. */
  moreFolders: number;
  moreFiles: number;
  /** The new memory's own name, and whether a memory by that key already exists. */
  name: string;
  exists: boolean;
}

/** The part of the tree a new memory at `key` lands in, for drawing where it goes. */
export function treeSlice(keys: string[], key: string, limit = 5): TreeSlice {
  const parts = key.split("/").filter(Boolean);
  const name = parts.pop() ?? "";
  const counts = folderCounts(keys);
  const existing = parts.map((_, i) => counts.has(parts.slice(0, i + 1).join("/")));
  const prefix = parts.length ? `${parts.join("/")}/` : "";
  const folders = new Set<string>();
  const files: string[] = [];
  for (const k of keys) {
    if (!k.startsWith(prefix)) continue;
    const rest = k.slice(prefix.length);
    const slash = rest.indexOf("/");
    if (slash === -1) {
      if (rest !== name) files.push(rest);
    } else {
      folders.add(rest.slice(0, slash));
    }
  }
  const allFolders = [...folders].sort();
  files.sort();
  return {
    path: parts,
    existing,
    folders: allFolders.slice(0, limit),
    files: files.slice(0, limit),
    moreFolders: Math.max(0, allFolders.length - limit),
    moreFiles: Math.max(0, files.length - limit),
    name,
    exists: keys.includes(key),
  };
}
