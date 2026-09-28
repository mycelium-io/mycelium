// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Examples for an agent's instructions: a few built in, and the ones a person
// saved, kept in this browser's localStorage. Saved examples are a per-viewer
// convenience, so a read or write that fails (private mode, blocked storage)
// just leaves the built-in ones.

export interface InstructionExample {
  /** Shown in the menu, and the handle suggested when the handle is still empty. */
  name: string;
  text: string;
  /** True for one this browser saved, which can be deleted. */
  saved?: boolean;
}

export const STORAGE_KEY = "mycelium.instruction-examples";

export const BUILT_IN: InstructionExample[] = [
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

export function loadSaved(): InstructionExample[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (e): e is InstructionExample =>
          !!e && typeof e.name === "string" && typeof e.text === "string" && !!e.name.trim(),
      )
      .map((e) => ({ name: e.name, text: e.text, saved: true }));
  } catch {
    return [];
  }
}

function store(list: InstructionExample[]): void {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(list.map(({ name, text }) => ({ name, text }))),
    );
  } catch {
    // Storage blocked or full: the example lasts until the page closes.
  }
}

/** Save an example under ``name``, replacing one saved under the same name. */
export function saveExample(name: string, text: string): InstructionExample[] {
  const clean = name.trim();
  const next = [
    ...loadSaved().filter((e) => e.name !== clean),
    { name: clean, text: text.trim(), saved: true },
  ];
  store(next);
  return next;
}

export function deleteExample(name: string): InstructionExample[] {
  const next = loadSaved().filter((e) => e.name !== name);
  store(next);
  return next;
}
