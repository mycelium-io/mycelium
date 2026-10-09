// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What to hand an agent so it reads something for itself: the CLI commands
 * that fetch it, ready to paste into its session. A person points an agent at
 * a memory, a task or a room this way rather than pasting what it says, so
 * the agent reads the current version, and from the hub, not a copy.
 *
 * Every command here is checked against the real CLI by `cli_prose`, like any
 * `mycelium …` text the frontend shows.
 */

/** A value as the shell reads it: bare when it is plain, quoted when not. */
function arg(value: string): string {
  return /^[\w./:@-]+$/.test(value) ? value : `'${value.replace(/'/g, `'\\''`)}'`;
}

/** Read one memory. */
export function memoryCommand(room: string, key: string): string {
  return `mycelium memory get ${arg(key)} --room ${arg(room)}`;
}

/** Read a task: the row, then the conversation in its thread. */
export function taskCommand(room: string, key: string): string {
  return [
    `mycelium memory get ${arg(key)} --room ${arg(room)}`,
    `mycelium board messages ${arg(key)} --room ${arg(room)}`,
  ].join("\n");
}

/** Catch up on a room: its board, then what was said lately. */
export function roomCommand(room: string): string {
  return [`mycelium board --room ${arg(room)}`, `mycelium room messages --room ${arg(room)}`].join("\n");
}
