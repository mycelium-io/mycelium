// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What people come to a room wanting, mapped to the engine that does it.
 *
 * The engines (conductor, aligner, synthesizer) are how the room works; these
 * are how a person asks for it. Each intent says in one sentence when you
 * would reach for it, which agents it needs, and the summon it sends, so
 * nobody has to know an engine's name or its grammar to use it.
 */

export type IntentId = "review" | "split" | "settle" | "catch-up";

export interface IntentRole {
  /** The role's name in the summon, in order. */
  id: string;
  /** How the picker labels it. */
  label: string;
}

export interface Intent {
  id: IntentId;
  label: string;
  /** When you would reach for it, in one sentence. */
  when: string;
  /** What happens once it starts, in one sentence. */
  then: string;
  /** Named roles, each one agent; empty for an intent that takes a group. */
  roles: IntentRole[];
  /** For a group intent: how many agents it needs at least (0 for none). */
  minGroup: number;
  /** The message that starts it, in the task's thread. */
  summon: (picks: { roles: Record<string, string>; group: string[] }, note: string) => string;
}

const handles = (list: string[]) => list.map(h => `@${h}`).join(" ");
const colon = (note: string) => (note.trim() ? `: ${note.trim()}` : "");

export const INTENTS: Intent[] = [
  {
    id: "review",
    label: "Get it reviewed",
    when: "One agent does the work and another checks it, for real.",
    then: "The author builds it on a branch; the reviewer runs it and sends findings back until it holds up.",
    roles: [
      { id: "author", label: "Who does it" },
      { id: "reviewer", label: "Who checks it" },
    ],
    minGroup: 0,
    summon: ({ roles }, note) =>
      `@conductor review @${roles.author} @${roles.reviewer}${colon(note) || ": the task above"}`,
  },
  {
    id: "split",
    label: "Split it up",
    when: "The task is big enough for several agents at once.",
    then: "Each agent says what it would take, then the first one splits the task into parts, one each.",
    roles: [],
    minGroup: 2,
    summon: ({ group }, note) => `@conductor swarm ${handles(group)}${colon(note) || ": the task above"}`,
  },
  {
    id: "settle",
    label: "Settle it",
    when: "Two or more agents want different things and neither is simply wrong.",
    then: "The aligner finds what they disagree on and brokers offers until they agree, or says they can't.",
    roles: [],
    minGroup: 2,
    summon: ({ group }, note) => `@aligner ${handles(group)}${colon(note)}`,
  },
  {
    id: "catch-up",
    label: "Catch me up",
    when: "You've been away and want what happened, not the whole thread.",
    then: "The synthesizer reads what was said since it last looked and writes a short briefing.",
    roles: [],
    minGroup: 0,
    summon: (_picks, note) => `@synthesizer catch me up${colon(note)}`,
  },
];

export function intentById(id: IntentId): Intent {
  const intent = INTENTS.find(i => i.id === id);
  if (!intent) throw new Error(`no intent ${id}`);
  return intent;
}

/** Whether the picks are enough to start: every role filled with a distinct agent, and the group big enough. */
export function ready(intent: Intent, picks: { roles: Record<string, string>; group: string[] }): boolean {
  const chosen = intent.roles.map(r => picks.roles[r.id]).filter(Boolean);
  if (chosen.length !== intent.roles.length) return false;
  if (new Set(chosen).size !== chosen.length) return false;
  return picks.group.length >= intent.minGroup;
}
