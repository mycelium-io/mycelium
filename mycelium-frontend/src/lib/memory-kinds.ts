// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The kinds of memory a room keeps, as far as the app's editor needs them:
 * which kinds a person edits here, and what to say about the ones they don't.
 *
 * A copy of contracts/memory-kinds.json's kinds (the hub checks every write
 * against the full table, `services/memory_kinds.py`), held to it by
 * memory-kinds.test.ts. A key's kind is the first whose pattern matches it:
 * `*` is one part of a key, `**` any number of parts.
 */

export type MemoryEdit = "body" | "field" | "none";

export interface MemoryKind {
  id: string;
  patterns: string[];
  edit: MemoryEdit;
  /** The frontmatter field a `field` kind's text is drawn from. */
  source?: string;
  /** What the hub says when a write to an `edit: none` kind is refused. */
  says?: string;
}

export const MEMORY_KINDS: MemoryKind[] = [
  {
    id: "upload",
    patterns: ["uploads/**"],
    edit: "none",
    says: "An upload is its file, and can't be edited. Upload the file again to replace it.",
  },
  { id: "agent", patterns: ["agents/*"], edit: "body" },
  { id: "protocol", patterns: ["protocols/*"], edit: "body" },
  { id: "setting", patterns: ["settings/*"], edit: "body" },
  { id: "skill", patterns: ["skills/*"], edit: "body" },
  { id: "thread", patterns: ["threads/*"], edit: "body" },
  { id: "task", patterns: ["work/**", "decisions/**", "status/**", "failed/**"], edit: "body" },
  { id: "summary", patterns: ["context/summary/**"], edit: "field", source: "contract" },
  { id: "decision", patterns: ["context/decision/**"], edit: "field", source: "decision" },
  { id: "synthesis", patterns: ["context/synthesis"], edit: "body" },
  {
    id: "standing",
    patterns: ["context/standing"],
    edit: "none",
    says: "Mycelium writes this after every step of a flow, so it can't be edited.",
  },
  {
    id: "episode_record",
    patterns: ["log/episodes/*"],
    edit: "none",
    says: "This is the record of a flow's run, written as it runs, so it can't be edited.",
  },
  { id: "memory", patterns: ["**"], edit: "body" },
];

function compile(pattern: string): RegExp {
  const escape = (s: string) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]+");
  return new RegExp(`^${pattern.split("**").map(escape).join(".+")}$`);
}

const COMPILED = MEMORY_KINDS.map((kind) => ({ kind, res: kind.patterns.map(compile) }));

/** The kind of the memory at `key`. */
export function kindOf(key: string): MemoryKind {
  return COMPILED.find(({ res }) => res.some((re) => re.test(key)))!.kind;
}

/** Why the editor doesn't offer to edit `kind`'s text, or null when it does. */
export function notEditable(kind: MemoryKind): string | null {
  if (kind.edit === "none") return kind.says ?? "This memory can't be edited.";
  if (kind.edit === "field") {
    const what = kind.id === "summary" ? "summary" : "decision";
    return `This text is made from the ${what} kept in its ${kind.source} field, so it isn't edited here.`;
  }
  return null;
}
