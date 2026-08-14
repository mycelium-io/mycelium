// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The coordination board is a live projection over the room's event ledger
// (concerns / actions / source_events over L9) — see issue #493. That ledger
// doesn't exist yet, so this module is the seam: `projectBoard()` derives board
// rows from data we already have (the compiled plan, the agent roster, the
// negotiation episodes), and stitches in a few sample archetypes so the whole
// idea reads even in a sparse room. When the real projection endpoint lands,
// only this file swaps — the board component consumes `BoardItem[]` either way.

import type { AgentSummary, EpisodeSummary, PlanTask } from "@/lib/api";

/** Where a row lives. The lens (not the raw state) is what the board groups by. */
export type Lens = "needs" | "flight" | "resolved";

/** Concern/action lifecycle from the epic: open → claimed → in_progress →
 *  in_review → resolved | blocked. */
export type ItemState =
  | "open"
  | "claimed"
  | "in_progress"
  | "in_review"
  | "resolved"
  | "blocked";

/** The row archetype — drives the leading glyph, tone, and which verbs show. */
export type ItemKind = "decision" | "blocked" | "review" | "action" | "concern";

export interface Owner {
  handle: string;
  /** Agents wear the accent + 🤖; the human stays neutral + 🧑. */
  kind: "agent" | "human";
  /** Live on the room channel right now (herdr presence). */
  present?: boolean;
}

export type CiState = "green" | "running" | "failed";

export interface WorkLink {
  branch?: string;
  pr?: { number: number; state: "draft" | "open" | "merged" };
  ci?: CiState;
}

/** Tie to GitHub by reference, not identity — a link, never a mirror. */
export interface GithubLink {
  issue?: number;
  state?: "open" | "closed";
}

export interface BoardItem {
  /** Short, human-quotable id (the ledger event's short hash), e.g. "d3f". */
  id: string;
  kind: ItemKind;
  state: ItemState;
  title: string;
  detail?: string;
  owner?: Owner;
  work?: WorkLink;
  github?: GithubLink;
  /** A decision offers inline choices ("15m" / "60m") plus a reply affordance. */
  choices?: string[];
  /** What this item blocks, or what it's waiting on (the dependency edge). */
  blocks?: string;
  waitingOn?: string;
  /** Where the row came from — an agent, a consensus, a PR, a human capture. */
  provenance?: string;
  /** Relative age label ("40m", "1h") for the ledger event. */
  age?: string;
  /** Human attention required — the row surfaces under the "Needs you" lens. */
  needsYou?: boolean;
  /** A one-line note shown on resolved rows ("PR #499 merged"). */
  note?: string;
  /** Illustrative archetype, not derived from this room's real state. Rendered
   *  with a faint "sample" tag so the sketch never masquerades as live data. */
  sample?: boolean;
}

/** Which lens a row belongs under. Resolved wins, then human-attention, then
 *  everything active falls through to the in-flight column. */
export function lensOf(item: BoardItem): Lens {
  if (item.state === "resolved") return "resolved";
  if (item.needsYou) return "needs";
  return "flight";
}

export interface BoardInput {
  tasks: PlanTask[];
  agents: AgentSummary[];
  episodes: EpisodeSummary[];
}

function isLiveEpisode(ep: EpisodeSummary): boolean {
  const s = ep.subkind ?? ep.outcome;
  return s !== "converged" && s !== "resolved" && s !== "rejected";
}

// A stable pseudo-owner pick so a task keeps the same agent across re-projections
// (no Date.now()/random — the board re-derives on every poll and must be stable).
function ownerFor(agents: AgentSummary[], seed: number): Owner | undefined {
  if (agents.length === 0) return undefined;
  const a = agents[seed % agents.length];
  return { handle: a.handle, kind: "agent", present: seed % 3 !== 0 };
}

// The sample archetypes from the epic mock — one of each row shape the real
// ledger will fill (decision that needs a reply, a blocked item waiting on an
// issue, a PR wanting review). Only appended when the room's real data doesn't
// already cover that archetype, so a live room shows itself first.
function sampleItems(agents: AgentSummary[]): BoardItem[] {
  const agentY = agents[0]?.handle ?? "agent-y";
  const agentZ = agents[1]?.handle ?? "agent-z";
  return [
    {
      id: "d3f",
      kind: "decision",
      state: "open",
      title: "JWT TTL — 15m or 60m?",
      choices: ["15m", "60m"],
      owner: { handle: agentY, kind: "agent", present: true },
      provenance: `from ${agentY}`,
      age: "6m",
      needsYou: true,
      sample: true,
    },
    {
      id: "a91",
      kind: "blocked",
      state: "blocked",
      title: "Enable thin-spoke join",
      waitingOn: "#502",
      github: { issue: 502, state: "open" },
      age: "40m",
      needsYou: true,
      sample: true,
    },
    {
      id: "7c2",
      kind: "review",
      state: "in_review",
      title: `${agentZ} opened a PR, wants eyes`,
      owner: { handle: agentZ, kind: "agent", present: true },
      work: { branch: "feat/path-fix", pr: { number: 504, state: "open" }, ci: "green" },
      provenance: `from ${agentZ}`,
      age: "12m",
      needsYou: true,
      sample: true,
    },
    {
      id: "e45",
      kind: "action",
      state: "in_progress",
      title: "Cache TTL sweep",
      owner: { handle: "julia", kind: "human", present: true },
      work: { branch: "feat/cache", ci: "running" },
      age: "3m",
      sample: true,
    },
    {
      id: "b90",
      kind: "action",
      state: "resolved",
      title: "Fix path traversal in loader",
      owner: { handle: agentZ, kind: "agent", present: false },
      work: { branch: "fix/traversal", pr: { number: 499, state: "merged" }, ci: "green" },
      note: "PR #499 merged",
      age: "1h",
      sample: true,
    },
  ];
}

/** Project the room's real state into board rows, then top up with sample
 *  archetypes for any row shape the room doesn't yet exercise. */
export function projectBoard(input: BoardInput): BoardItem[] {
  const { tasks, agents, episodes } = input;
  const items: BoardItem[] = [];

  // A live negotiation is a decision the human can steer toward — surface it at
  // the top of "Needs you" as a review row pointing at the aligner.
  for (const ep of episodes.filter(isLiveEpisode)) {
    items.push({
      id: ep.short_id,
      kind: "review",
      state: "in_review",
      title: ep.topic || "negotiation in flight",
      detail: "the aligner is brokering — reply to move it",
      provenance: "from @aligner",
      needsYou: true,
    });
  }

  // Compiled plan tasks are the closest thing to the action ledger today: open
  // tasks become in-flight actions with a (round-robin) owner; done tasks
  // become resolved rows that auto-hide.
  tasks.forEach((t, i) => {
    items.push({
      id: t.id.slice(0, 3) || t.slug.slice(0, 3),
      kind: "action",
      state: t.done ? "resolved" : "in_progress",
      title: t.text,
      owner: t.done ? undefined : ownerFor(agents, i),
      provenance: `plan/${t.slug}.md`,
      note: t.done ? "task complete" : undefined,
    });
  });

  // Fill in the archetypes the real data doesn't cover, so the full board vision
  // is legible in any room.
  const haveKinds = new Set(items.map((it) => it.kind));
  const haveResolved = items.some((it) => it.state === "resolved");
  for (const s of sampleItems(agents)) {
    const coversNewKind = !haveKinds.has(s.kind);
    const coversResolved = s.state === "resolved" && !haveResolved;
    if (coversNewKind || coversResolved) items.push(s);
  }

  return items;
}

/** The header summary: N need you · M in flight · K resolved. */
export function boardCounts(items: BoardItem[]): Record<Lens, number> {
  const counts: Record<Lens, number> = { needs: 0, flight: 0, resolved: 0 };
  for (const it of items) counts[lensOf(it)] += 1;
  return counts;
}
