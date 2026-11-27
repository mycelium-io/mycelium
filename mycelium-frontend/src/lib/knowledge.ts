// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What a room's team learned, as the app reads it.
 *
 * The hub's knowledge graph (`GET /rooms/{room}/knowledge`,
 * `services/knowledge.py`): memories with a `kind` (a fact, a finding or a
 * dead end), the task each was learned in, and
 * `derived-from`, the relation that says what each came from. A memory is open
 * while someone is still working on it and settled once it holds. A task is a
 * lens on the same graph.
 */

export type KnowledgeKind = "fact" | "finding" | "dead-end";

export interface KnowledgeTask {
  key: string;
  title: string;
}

export interface Knowledge {
  key: string;
  kind: KnowledgeKind;
  title: string;
  /** Who wrote it: a person, an agent, or a subagent (`builder:retry`). */
  by: string;
  /** The task it was learned in, or "" for none. */
  task: string;
  open?: boolean;
  /** Keys of the memories it came from. */
  derivedFrom?: string[];
  /** Keys of memories it bears on without coming from them. */
  relatesTo?: string[];
  tags?: string[];
  /** When it last changed (ISO), or "". */
  updatedAt: string;
}

export interface KnowledgeGraph {
  tasks: KnowledgeTask[];
  memories: Knowledge[];
}

/** One memory as the hub sends it. */
export interface KnowledgeWire {
  key: string;
  kind: KnowledgeKind;
  title: string;
  by: string;
  task: string | null;
  open: boolean;
  derived_from: string[];
  relates_to: string[];
  tags: string[];
  updated_at: string;
  in_task?: boolean | null;
}

export function fromWire(m: KnowledgeWire): Knowledge {
  return {
    key: m.key,
    kind: m.kind,
    title: m.title,
    by: m.by,
    task: m.task ?? "",
    open: m.open,
    derivedFrom: m.derived_from,
    relatesTo: m.relates_to,
    tags: m.tags,
    updatedAt: m.updated_at,
  };
}

/** How many of a set are still open. */
export function openCount(memories: Knowledge[]): number {
  return memories.filter((m) => m.open).length;
}
