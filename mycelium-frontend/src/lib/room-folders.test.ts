// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import type { Room } from "@/lib/api";
import {
  addFolder,
  deleteFolder,
  folderOf,
  groupRooms,
  moveFolder,
  moveRoom,
  renameFolder,
  toggleFolder,
  type RoomFolders,
} from "@/lib/room-folders";

const room = (name: string) => ({ name }) as Room;
const layout: RoomFolders = {
  folders: [
    { id: "a", name: "Payments", rooms: ["checkout", "refunds"] },
    { id: "b", name: "Side", rooms: ["scratch"] },
  ],
};

describe("room folders", () => {
  it("splits the list into your folders and the rest, keeping the list's order", () => {
    const list = [room("refunds"), room("alpha"), room("checkout")];
    const { groups, loose } = groupRooms(list, layout);
    expect(groups.map(g => [g.folder.name, g.rooms.map(r => r.name)])).toEqual([
      ["Payments", ["refunds", "checkout"]],
      ["Side", []],
    ]);
    expect(loose.map(r => r.name)).toEqual(["alpha"]);
  });

  it("leaves out a filed name that no longer names a room", () => {
    const { groups } = groupRooms([room("checkout")], layout);
    expect(groups[0].rooms.map(r => r.name)).toEqual(["checkout"]);
  });

  it("moves a room between folders, and out of them", () => {
    const moved = moveRoom(layout, "checkout", "b");
    expect(folderOf(moved, "checkout")?.id).toBe("b");
    expect(moved.folders[0].rooms).toEqual(["refunds"]);
    expect(folderOf(moveRoom(moved, "checkout", null), "checkout")).toBeUndefined();
  });

  it("deletes a folder and leaves its rooms filed nowhere", () => {
    const after = deleteFolder(layout, "a");
    expect(after.folders.map(f => f.id)).toEqual(["b"]);
    expect(folderOf(after, "checkout")).toBeUndefined();
  });

  it("adds, renames, folds and reorders folders", () => {
    const added = addFolder(layout, "  Infra ", "c");
    expect(added.folders.at(-1)).toEqual({ id: "c", name: "Infra", rooms: [] });
    expect(renameFolder(added, "c", "Platform").folders.at(-1)?.name).toBe("Platform");
    // A blank name is no rename.
    expect(renameFolder(added, "c", "  ")).toBe(added);
    expect(toggleFolder(layout, "a").folders[0].collapsed).toBe(true);
    expect(moveFolder(layout, "b", -1).folders.map(f => f.id)).toEqual(["b", "a"]);
    expect(moveFolder(layout, "a", -1)).toBe(layout);
  });
});
