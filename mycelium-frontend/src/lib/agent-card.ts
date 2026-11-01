// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What a member's card says about its state, and whether it shows the agent's
// screen. The card itself is `components/agent-card.tsx`.

import type { PresenceMember } from "@/lib/api";

export type MemberKind = "agent" | "person" | "engine";

export type MemberStateKey = "working" | "waiting" | "cant_reply" | "idle" | "not_running" | "here" | "away" | "engine";

export interface MemberState {
  key: MemberStateKey;
  word: string;
  /** A CSS color for the word and its dot. */
  tone: string;
}

const STATES: Record<MemberStateKey, Omit<MemberState, "key">> = {
  working: { word: "Working", tone: "var(--accent)" },
  waiting: { word: "Waiting for input", tone: "var(--yellow)" },
  cant_reply: { word: "Can't reply", tone: "var(--red)" },
  idle: { word: "Idle", tone: "var(--muted-foreground)" },
  not_running: { word: "Not running", tone: "var(--faint)" },
  here: { word: "Here", tone: "var(--green)" },
  away: { word: "Away", tone: "var(--faint)" },
  engine: { word: "Engine", tone: "var(--muted-foreground)" },
};

const state = (key: MemberStateKey, word?: string): MemberState => ({ key, ...STATES[key], ...(word ? { word } : {}) });

/** A member's state, in a word and a color. An agent that can't reply says so
 *  before anything else, since it's the one that needs a person; one stopped at
 *  a prompt is waiting for input. An engine says what kind it is. */
export function memberState(kind: MemberKind, presence: PresenceMember | undefined, engineKind?: string | null): MemberState {
  if (kind === "engine") return state("engine", engineKind ?? undefined);
  if (kind === "person") return presence ? state("here") : state("away");
  if (!presence) return state("not_running");
  if (presence.can_reply === false) return state("cant_reply");
  if (presence.status === "working") return state("working");
  if (presence.status === "blocked") return state("waiting");
  return state("idle");
}

/** The states whose screen tells you something. An idle agent's is mostly a blank prompt. */
const TELLING = new Set<MemberStateKey>(["working", "waiting", "cant_reply"]);

/**
 * Whether the card asks for an agent's screen. Only an agent's, only in a state
 * its screen says something in, and only one that runs on this machine: the app
 * reads the screen locally, and it never goes to the hub. The app answers which
 * agents are on this machine (`useAgentScreen`'s `notHere`); this is the other half.
 */
export function wantsScreen(kind: MemberKind, s: MemberState): boolean {
  return kind === "agent" && TELLING.has(s.key);
}
