// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Templates for an agent's instructions: a few built in, and the ones a person
// saved, kept in this browser's localStorage. Saved templates are a per-viewer
// convenience, so a read or write that fails (private mode, blocked storage)
// just leaves the built-in ones.

export interface InstructionTemplate {
  /** Shown in the menu, and the handle suggested when the handle is still empty. */
  name: string;
  text: string;
  /** True for one this browser saved, which can be deleted. */
  saved?: boolean;
}

export const STORAGE_KEY = "mycelium.instruction-templates";

export const BUILT_IN: InstructionTemplate[] = [
  {
    name: "reviewer",
    text:
      "You review changes for correctness. When someone asks for a review, read the diff, " +
      "say what is right and what has to change, and name the author so they hear it. " +
      "Be specific and brief.",
  },
  {
    name: "implementer",
    text:
      "You take tasks off the board and do them for real in this folder. Claim a task, " +
      "work it, post what you did in its thread, and ask a teammate to review before you " +
      "resolve it.",
  },
  {
    name: "tester",
    text:
      "You write and run tests. For each task you pick up, add tests that would have caught " +
      "the problem, run the suite, and post the results and anything that failed.",
  },
  {
    name: "researcher",
    text:
      "You answer questions by reading the code and docs in this folder. Reply with what you " +
      "found and where (file and line), and say plainly when you are not sure.",
  },
  {
    name: "docs",
    text:
      "You keep the docs current. When a change lands, update the docs it affects, in plain " +
      "language, and post a short summary of what changed.",
  },
];

export function loadSaved(): InstructionTemplate[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (t): t is InstructionTemplate =>
          !!t && typeof t.name === "string" && typeof t.text === "string" && !!t.name.trim(),
      )
      .map((t) => ({ name: t.name, text: t.text, saved: true }));
  } catch {
    return [];
  }
}

function store(list: InstructionTemplate[]): void {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(list.map(({ name, text }) => ({ name, text }))),
    );
  } catch {
    // Storage blocked or full: the template lasts until the page closes.
  }
}

/** Save a template under ``name``, replacing one saved under the same name. */
export function saveTemplate(name: string, text: string): InstructionTemplate[] {
  const clean = name.trim();
  const next = [
    ...loadSaved().filter((t) => t.name !== clean),
    { name: clean, text: text.trim(), saved: true },
  ];
  store(next);
  return next;
}

export function deleteTemplate(name: string): InstructionTemplate[] {
  const next = loadSaved().filter((t) => t.name !== name);
  store(next);
  return next;
}
