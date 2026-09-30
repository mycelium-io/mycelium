// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The composer's `/` commands: what each one takes, and where the cursor is
// among its arguments while it is being typed.
//
// A command is the first word of a message and runs rather than posts. Each
// declares its arguments in order, so the composer can draw the signature over
// the box with the one being typed highlighted, offer that argument's values,
// and say which one is missing, from one list rather than one parser per
// command. The last argument can take the rest of the line (`/task` reads its
// own grammar out of it).

/** Where an argument's values come from. The composer resolves each one. */
export type ChoiceSource = "harness" | "folder" | "machine" | "engine" | "memory-key";

export interface CommandArg {
  name: string;
  /** What it is, said under the signature while it is being typed. */
  about: string;
  optional?: boolean;
  /** Takes everything from here to the end of the message. Last argument only. */
  rest?: boolean;
  /** A new name rather than a reference: `@` here names, it doesn't mention. */
  names?: boolean;
  choices?: ChoiceSource;
  /** What to say when it is left out, when "Say the <name>" won't do. */
  missing?: string;
}

export interface ComposerCommand {
  name: string;
  about: string;
  args: CommandArg[];
}

export const COMPOSER_COMMANDS: ComposerCommand[] = [
  {
    name: "task",
    about: "add it to the board for someone to pick up",
    args: [
      {
        name: "what",
        rest: true,
        about: "The task, with @owner, !urgent and #tag anywhere in it",
        missing: "Say what it is",
      },
    ],
  },
  {
    name: "swarm",
    about: "have a team of agents work on it now",
    args: [{ name: "what", rest: true, about: "What the team should work on", missing: "Say what it is" }],
  },
  {
    name: "memory",
    about: "write something down for the room to keep",
    args: [
      {
        name: "key",
        optional: true,
        choices: "memory-key",
        about: "Where it goes, as folder/name. Leave everything out to open the editor",
      },
      {
        name: "text",
        rest: true,
        optional: true,
        about: "What to write down. Markdown works. Leave it out to finish it in the editor",
      },
    ],
  },
  {
    name: "agent",
    about: "start a coding agent on your machine in this room",
    args: [
      { name: "handle", names: true, about: "What the room calls it, as in @scout" },
      { name: "harness", choices: "harness", about: "Which agent program to start" },
      { name: "folder", optional: true, choices: "folder", about: "Where it works. The machine's first folder if left out" },
      { name: "machine", optional: true, choices: "machine", about: "Which machine. The first one that can start it if left out" },
    ],
  },
  {
    name: "engine",
    about: "add an engine the hub runs, like the aligner",
    args: [
      { name: "kind", choices: "engine", about: "What it does" },
      { name: "handle", optional: true, names: true, about: "What the room calls it. Its kind if left out" },
    ],
  },
];

export function commandNamed(name: string): ComposerCommand | undefined {
  return COMPOSER_COMMANDS.find((c) => c.name === name);
}

/** `/agent <handle> <harness> [folder] [machine]` */
export function usage(command: ComposerCommand): string {
  const args = command.args.map((a) => {
    const name = a.rest ? `${a.name}…` : a.name;
    return a.optional ? `[${name}]` : `<${name}>`;
  });
  return [`/${command.name}`, ...args].join(" ");
}

export interface Span {
  value: string;
  start: number;
  end: number;
}

export interface ParsedCommand {
  command: ComposerCommand;
  /** One per declared argument, in order; absent past what was typed. */
  args: (Span | undefined)[];
  /** The argument the cursor is in, or null on the command's own name or past the last. */
  active: number | null;
  /** The word under the cursor (empty in a gap), which a completion replaces. */
  word: Span | null;
}

/** The command a message runs, and where the cursor is in it; null for a message. */
export function parseCommand(text: string, cursor: number = text.length): ParsedCommand | null {
  const head = text.match(/^\/([a-z0-9._-]+)(?=\s|$)/i);
  if (!head) return null;
  const command = commandNamed(head[1].toLowerCase());
  if (!command) return null;

  const nameEnd = head[0].length;
  const words: Span[] = [];
  for (const m of text.slice(nameEnd).matchAll(/\S+/g)) {
    const start = nameEnd + (m.index ?? 0);
    words.push({ value: m[0], start, end: start + m[0].length });
  }

  const restAt = command.args.findIndex((a) => a.rest);
  const args: (Span | undefined)[] = command.args.map((arg, i) => {
    if (i === restAt) {
      const taken = words.slice(i);
      if (taken.length === 0) return undefined;
      const start = taken[0].start;
      const end = taken[taken.length - 1].end;
      return { value: text.slice(start, end), start, end };
    }
    return words[i];
  });

  if (cursor <= nameEnd) return { command, args, active: null, word: null };

  // The word the cursor touches, or the gap it sits in: then the next word to type.
  let index = words.findIndex((w) => cursor >= w.start && cursor <= w.end);
  let word: Span;
  if (index >= 0) {
    word = words[index];
  } else {
    index = words.filter((w) => w.end < cursor).length;
    word = { value: "", start: cursor, end: cursor };
  }
  const argIndex = restAt >= 0 && index >= restAt ? restAt : index;
  const active = argIndex < command.args.length ? argIndex : null;
  return { command, args, active, word: active === null ? null : word };
}

/** What stops a command from running: the first argument it needs that isn't there. */
export function missingArg(parsed: ParsedCommand): string | null {
  const i = parsed.command.args.findIndex((a, n) => !a.optional && !parsed.args[n]?.value);
  if (i < 0) return null;
  const arg = parsed.command.args[i];
  return `${arg.missing ?? `Say the ${arg.name}`}: ${usage(parsed.command)}`;
}

/** The value typed for a named argument, trimmed, or "". */
export function argValue(parsed: ParsedCommand, name: string): string {
  const i = parsed.command.args.findIndex((a) => a.name === name);
  return i < 0 ? "" : (parsed.args[i]?.value ?? "").trim();
}

// ── A conductor summon ───────────────────────────────────────────────────────
//
// `@conductor gated @ana @ben: ship the fix` is a message, not a command: the
// conductor reads it where it lands (the first word that isn't a mention names
// the flow, the mentions take its roles in order, the rest is what it's about).
// What the composer adds is the grammar, drawn as it's typed, with the flow's
// own role names in the member slots once one is chosen.

/** A flow as the composer needs it (the hub's `ProtocolSummary`). */
export interface FlowSpec {
  name: string;
  description: string;
  roles: string[];
}

export type SummonPart = "flow" | "member" | "ask";

export interface ParsedSummon {
  /** The conductor's handle, as mentioned. */
  engine: string;
  flow: Span | null;
  /** The flow named, when the room has one by that name. */
  protocol: FlowSpec | undefined;
  /** The members named, in order: each takes the next role. */
  members: Span[];
  /** Whether anything has been said about what it's for. */
  asked: boolean;
  active: SummonPart | null;
  /** Which member slot the cursor is on, when `active` is "member". */
  slot: number;
  word: Span | null;
}

const trimFlow = (word: string) => word.replace(/[:,;]+$/, "").toLowerCase();

/** A summon of one of `engines` being written, and where the cursor is in it; null otherwise. */
export function parseSummon(
  text: string,
  cursor: number,
  engines: readonly string[],
  flows: readonly FlowSpec[],
): ParsedSummon | null {
  const head = text.match(/^@([a-z0-9._-]+)(?=\s|$)/i);
  if (!head || !engines.includes(head[1].toLowerCase())) return null;
  const headEnd = head[0].length;
  const words: Span[] = [];
  for (const m of text.slice(headEnd).matchAll(/\S+/g)) {
    const start = headEnd + (m.index ?? 0);
    words.push({ value: m[0], start, end: start + m[0].length });
  }
  const isMention = (w: Span) => w.value.startsWith("@");
  const flowAt = words.findIndex((w) => !isMention(w));
  const flow = flowAt >= 0 ? words[flowAt] : null;
  const members = words.filter(isMention);
  const protocol = flow ? flows.find((f) => f.name === trimFlow(flow.value)) : undefined;
  const asked = words.some((w, i) => i > flowAt && flowAt >= 0 && !isMention(w));
  const base = { engine: head[1].toLowerCase(), flow, protocol, members, asked };

  if (cursor <= headEnd) return { ...base, active: null, slot: 0, word: null };

  const at = words.findIndex((w) => cursor >= w.start && cursor <= w.end);
  const before = (w: Span) => w.end < cursor;
  if (at >= 0) {
    const w = words[at];
    if (isMention(w)) return { ...base, active: "member", slot: words.slice(0, at).filter(isMention).length, word: w };
    return { ...base, active: at === flowAt ? "flow" : "ask", slot: 0, word: w };
  }
  const gap = { value: "", start: cursor, end: cursor };
  if (!flow || !before(flow)) return { ...base, active: "flow", slot: 0, word: gap };
  if (words.some((w, i) => i > flowAt && before(w) && !isMention(w))) {
    return { ...base, active: "ask", slot: 0, word: gap };
  }
  const slot = members.filter(before).length;
  // A flow with roles is done taking members once each has one.
  if (protocol && protocol.roles.length > 0 && slot >= protocol.roles.length) {
    return { ...base, active: "ask", slot: 0, word: gap };
  }
  return { ...base, active: "member", slot, word: gap };
}

export interface Choice {
  value: string;
  about?: string;
  /** Part of a value, like a folder: picking it keeps the cursor in the word. */
  open?: boolean;
}

/**
 * Where a memory can go, for the word typed so far: the folders under it
 * (open, so picking one lists what's inside) and the memories already there,
 * which a write would replace.
 */
export function memoryKeyChoices(keys: string[], standard: readonly string[], typed: string): Choice[] {
  const slash = typed.lastIndexOf("/");
  const base = slash >= 0 ? typed.slice(0, slash + 1) : "";
  const folders = new Map<string, number>();
  const here: string[] = [];
  for (const key of keys) {
    if (!key.startsWith(base)) continue;
    const rest = key.slice(base.length);
    const cut = rest.indexOf("/");
    if (cut < 0) here.push(key);
    else folders.set(base + rest.slice(0, cut + 1), (folders.get(base + rest.slice(0, cut + 1)) ?? 0) + 1);
  }
  if (!base) for (const f of standard) if (!folders.has(`${f}/`)) folders.set(`${f}/`, 0);
  const plural = (n: number) => (n === 1 ? "1 memory" : `${n} memories`);
  return [
    ...[...folders.entries()]
      .filter(([f]) => base || (f !== "agents/" && f !== "log/"))
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([value, n]) => ({ value, open: true, about: n ? `folder · ${plural(n)}` : "folder" })),
    ...here.sort().map((value) => ({ value, about: "already here · writing replaces it" })),
  ];
}

/** Choices matching what's typed so far: starts-with first, then contains. */
export function matchChoices(choices: Choice[], typed: string): Choice[] {
  const q = typed.toLowerCase();
  if (!q) return choices;
  const starts = choices.filter((c) => c.value.toLowerCase().startsWith(q));
  const contains = choices.filter((c) => !c.value.toLowerCase().startsWith(q) && c.value.toLowerCase().includes(q));
  return [...starts, ...contains];
}
