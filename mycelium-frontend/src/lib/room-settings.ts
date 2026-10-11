// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** A room's settings, as the settings page shows them.
 *
 *  The table is the hub's (`contracts/room-settings.json`, checked on every
 *  write to `settings/`); this copy adds what a person reads: a label, a line
 *  saying what it does, and a word for each choice. `room-settings.contract.test.ts`
 *  asserts the ids, kinds and options against the contract. */

import type { RoomSetting } from "@/lib/api";

export interface RoomSettingCopy {
  id: string;
  kind: "bool" | "int" | "set";
  options?: readonly string[];
  default?: readonly string[];
  label: string;
  help: string;
  /** What each option of a set reads as. */
  optionLabels?: Record<string, string>;
  /** The page section it sits in. */
  section: "Chat" | "Board" | "Agents";
}

export const ROOM_SETTINGS: readonly RoomSettingCopy[] = [
  {
    id: "chat-board-moves",
    kind: "set",
    options: ["filed", "claimed", "released", "blocked", "unblocked", "expired", "resolved"],
    default: ["filed", "resolved"],
    label: "Board moves shown in the chat",
    help: "Every move stays on the activity rail. The ones picked here also get a line in the chat.",
    optionLabels: {
      filed: "New",
      claimed: "Claimed",
      released: "Released",
      blocked: "Blocked",
      unblocked: "Unblocked",
      expired: "Expired",
      resolved: "Resolved",
    },
    section: "Chat",
  },
  {
    id: "dependency-gate",
    kind: "bool",
    label: "Tasks wait for what they depend on",
    help: "A task that depends on an unfinished one can't be claimed until that one is done. Claiming with force still takes it.",
    section: "Board",
  },
  {
    id: "worker-turns",
    kind: "int",
    label: "Worker turns in this room",
    help: "How many turns the hub's workers can take here in total, so workers asking each other can't run forever. A room can lower the hub's limit, not raise it.",
    section: "Agents",
  },
];

/** The board moves this room shows in its chat, from its settings (the
 *  default while they load). */
export function boardMovesInChat(settings: readonly RoomSetting[]): ReadonlySet<string> {
  const entry = settings.find((s) => s.id === "chat-board-moves");
  const value = entry && Array.isArray(entry.value) ? (entry.value as string[]) : null;
  return new Set(value ?? ROOM_SETTINGS[0].default ?? []);
}
