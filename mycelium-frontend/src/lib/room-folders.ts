// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A person's folders for their rooms list. Theirs alone: the hub keeps one
 * layout per handle (`/api/users/{handle}/room-folders`), and a room knows
 * nothing about the folders it is filed in, so two people can file the same
 * room differently. These are the pure operations on a layout; the sidebar
 * draws `groupRooms` and saves what the operations return.
 */

import type { Room } from "@/lib/api";

export interface RoomFolder {
  id: string;
  name: string;
  rooms: string[];
  collapsed?: boolean;
}

export interface RoomFolders {
  folders: RoomFolder[];
}

export const EMPTY_LAYOUT: RoomFolders = { folders: [] };

/** A folder's id: unique within one person's layout, which is all it needs. */
export function newFolderId(): string {
  return `f-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

/** The folder a room is filed in, if any. */
export function folderOf(layout: RoomFolders, room: string): RoomFolder | undefined {
  return layout.folders.find((f) => f.rooms.includes(room));
}

export interface FolderGroup {
  folder: RoomFolder;
  /** The folder's rooms that are on the list, in the list's order. */
  rooms: Room[];
}

/**
 * The rooms list split into the person's folders, in their order, and the
 * rooms filed nowhere. `rooms` arrives already filtered and ordered; a folder
 * keeps that order, and a name that no longer names a room is left out.
 */
export function groupRooms(rooms: Room[], layout: RoomFolders): { groups: FolderGroup[]; loose: Room[] } {
  const filed = new Map<string, string>();
  for (const folder of layout.folders) for (const room of folder.rooms) if (!filed.has(room)) filed.set(room, folder.id);
  const byFolder = new Map<string, Room[]>(layout.folders.map((f) => [f.id, []]));
  const loose: Room[] = [];
  for (const room of rooms) {
    const id = filed.get(room.name);
    if (id) byFolder.get(id)?.push(room);
    else loose.push(room);
  }
  return { groups: layout.folders.map((folder) => ({ folder, rooms: byFolder.get(folder.id) ?? [] })), loose };
}

export function addFolder(layout: RoomFolders, name: string, id = newFolderId()): RoomFolders {
  return { folders: [...layout.folders, { id, name: name.trim() || "Folder", rooms: [] }] };
}

export function renameFolder(layout: RoomFolders, id: string, name: string): RoomFolders {
  const clean = name.trim();
  if (!clean) return layout;
  return { folders: layout.folders.map((f) => (f.id === id ? { ...f, name: clean } : f)) };
}

/** Delete a folder. Its rooms stay, back in the list filed nowhere. */
export function deleteFolder(layout: RoomFolders, id: string): RoomFolders {
  return { folders: layout.folders.filter((f) => f.id !== id) };
}

export function toggleFolder(layout: RoomFolders, id: string): RoomFolders {
  return { folders: layout.folders.map((f) => (f.id === id ? { ...f, collapsed: !f.collapsed } : f)) };
}

/** File a room in a folder, out of whichever held it; `null` files it nowhere. */
export function moveRoom(layout: RoomFolders, room: string, to: string | null): RoomFolders {
  return {
    folders: layout.folders.map((f) => {
      const rest = f.rooms.filter((r) => r !== room);
      return f.id === to ? { ...f, rooms: [...rest, room] } : rest.length === f.rooms.length ? f : { ...f, rooms: rest };
    }),
  };
}

/** Move a folder up (-1) or down (+1) the list. */
export function moveFolder(layout: RoomFolders, id: string, delta: -1 | 1): RoomFolders {
  const at = layout.folders.findIndex((f) => f.id === id);
  const to = at + delta;
  if (at < 0 || to < 0 || to >= layout.folders.length) return layout;
  const folders = [...layout.folders];
  [folders[at], folders[to]] = [folders[to], folders[at]];
  return { folders };
}
