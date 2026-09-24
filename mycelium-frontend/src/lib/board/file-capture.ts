// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Filing a captured line as a real task on the hub. The board's capture bar and
// the composer's `/task` read the same grammar (`parseCapture`), so they file
// the same way: the task through the tasks route, which mints its thread, then
// whatever else the line set as ordinary fields.

import { createTask, writeFields, type Memory } from "@/lib/api";
import type { ParsedCapture } from "./capture";

/** The capture fields that ride along as ordinary board fields once the task exists. */
const EXTRA_FIELDS = ["priority", "tags", "issue", "blocked_by"] as const;

function slug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48)
      .replace(/-+$/, "") || "decision"
  );
}

/** The request a capture files as: who it is for, and where a decision lives. */
export function taskRequest(parsed: ParsedCapture, actor: string) {
  const owner = typeof parsed.fields.owner === "string" ? parsed.fields.owner.replace(/^@/, "") : "";
  const decision = parsed.fields.kind === "decision";
  return {
    title: parsed.title,
    handle: actor,
    ...(owner ? { assignee: owner } : {}),
    ...(decision ? { key: `decisions/${slug(parsed.title)}` } : {}),
  };
}

/** The fields to write onto the new task, beyond what creating it set. */
export function extraFields(parsed: ParsedCapture): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const name of EXTRA_FIELDS) {
    const value = parsed.fields[name];
    if (value === undefined || value === null) continue;
    if (name === "priority" && value === "normal") continue;
    out[name] = value;
  }
  return out;
}

/** File a captured line as a task in `roomName`; resolves to the task as written. */
export async function fileCapture(roomName: string, parsed: ParsedCapture, actor: string): Promise<Memory> {
  const task = await createTask(roomName, taskRequest(parsed, actor));
  const fields = extraFields(parsed);
  if (Object.keys(fields).length > 0) {
    await writeFields(roomName, { key: task.key, handle: actor, fields });
  }
  return task;
}
