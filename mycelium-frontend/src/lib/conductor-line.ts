// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A conductor post carries a structured line beside its prose
// (`conductor.LINE_KEY` on the hub): the prose is what the members read, the
// line is what a thread draws instead, so a run reads as its steps rather than
// as the prompts behind them. The line arrives two ways, like every message: on
// the live stream inside the L9 envelope's payload, and on a reload in the
// message's `metadata`.

export interface ConductorStep {
  id: string;
  to?: string;
  next?: string | Record<string, string>;
  end?: string;
}

export type ConductorLine =
  | {
      event: "open";
      protocol: string;
      description?: string;
      roles: Record<string, string>;
      members: string[];
      steps: ConductorStep[];
    }
  | {
      event: "turn";
      protocol: string;
      step: string;
      to: string;
      turn: number;
      cap: number;
      round?: number;
      rounds?: number;
      tell?: boolean;
      /** A second asking, of a member whose reply lacked what the step requires. */
      again?: boolean;
    }
  | { event: "edge"; step: string; who: string; stance: string | null; next: string }
  | { event: "select"; step: string; next: string | null; select: PickRecord }
  | { event: "tally"; step: string; next: string | null; tally: TallyRecord }
  | { event: "lock"; step: string; next: string | null; lock: LockRecord }
  | {
      event: "close";
      protocol: string;
      outcome: string;
      steps: number;
      reason: string;
      /** The option a run that picked ended on. */
      pick?: string;
      text?: string;
      /** The memory the run saved what it settled to (a shared summary, a
       *  decision); `null` when saving it failed, absent when nothing was saved. */
      memory?: string | null;
    };

/** A count the conductor made in code, asking nobody: of the points members
 *  have given so far, or of the words they gave different meanings to. */
export type TallyRecord =
  | {
      of: "points";
      round: number;
      max_rounds: number;
      outcome: "grew" | "settled" | "empty";
      /** Points this round added. */
      added: number;
      /** Points in all. */
      points: number;
      /** The rounds ran out while points were still coming. */
      capped: boolean;
    }
  | {
      of: "terms";
      round: number;
      max_rounds: number;
      outcome: "contested" | "clear";
      /** Words that were given a meaning. */
      words: number;
      /** Words used in different senses. */
      contested: string[];
      /** Who is asked to restate them. */
      asked?: string[];
    };

/** The shared summary the points were merged into, and where it was saved. */
export interface LockRecord {
  outcome: "locked" | "empty";
  memory: string | null;
  saved: boolean;
  points: number;
  /** Points stated by more than one member. */
  shared: number;
  /** Words still used in different senses. */
  contested: number;
  /** How done reads, as checks. */
  checks: number;
  /** Open items: everything flagged rather than settled. */
  flagged: number;
  /** Members who gave nothing. */
  quiet: string[];
}

/** One pick among the options, as a select step records it: the ratings
 *  table, the pick, and who is short of the bar. */
export interface PickRecord {
  outcome: "feasible" | "infeasible" | "stuck";
  pick: string | null;
  text: string;
  /** The bar, 0-100. */
  threshold: number;
  options: { label: string; text: string; authors: string[] }[];
  /** `{letter: {member: rating}}`; a member who gave none is absent. */
  table: Record<string, Record<string, number>>;
  cast: string[];
  ratings: Record<string, number>;
  lowest: number | null;
  missing: string[];
  least_happy: string | null;
}

/** An agreement a pick certified reads as success, like a flow that resolved. */
export function isSuccess(outcome: string): boolean {
  return outcome === "resolved" || outcome === "converged";
}

const EVENTS = new Set(["open", "turn", "edge", "select", "tally", "lock", "close"]);

function asLine(value: unknown): ConductorLine | null {
  if (!value || typeof value !== "object") return null;
  const event = (value as { event?: unknown }).event;
  return typeof event === "string" && EVENTS.has(event) ? (value as ConductorLine) : null;
}

/** The conductor line a message carries, or `null` when it carries none. */
export function conductorLineOf(message: {
  content?: unknown;
  metadata?: unknown;
}): ConductorLine | null {
  const fromMeta = asLine((message.metadata as { conductor?: unknown } | null | undefined)?.conductor);
  if (fromMeta) return fromMeta;
  let content = message.content;
  if (typeof content === "string") {
    if (!content.startsWith("{")) return null;
    try {
      content = JSON.parse(content);
    } catch {
      return null;
    }
  }
  const data = (
    (content as { l9?: { payload?: { data?: Record<string, unknown> } } } | null)?.l9?.payload
      ?.data ?? null
  );
  return asLine(data?.conductor);
}

/** One line of plain text for a conductor line, for surfaces that draw no widget. */
export function describeConductorLine(line: ConductorLine): string {
  switch (line.event) {
    case "open": {
      const cast = Object.entries(line.roles).map(([role, who]) => `${who} as ${role}`);
      if (line.members.length) cast.push(line.members.join(", "));
      return `Running ${line.protocol}${cast.length ? ` · ${cast.join(" · ")}` : ""}`;
    }
    case "turn": {
      const round = line.rounds ? ` · round ${line.round} of ${line.rounds}` : "";
      return `${line.step} → ${line.to} · turn ${line.turn} of ${line.cap}${round}`;
    }
    case "edge": {
      const said =
        line.stance === "accept"
          ? "accepted"
          : line.stance === "reject"
            ? "blocked"
            : line.stance === "silent"
              ? "did not answer"
              : "stated no stance";
      return `${line.step}: ${line.who} ${said}, on to ${line.next}`;
    }
    case "select":
      return `${line.step}: ${pickSummary(line.select)}`;
    case "tally":
      return tallySummary(line.tally);
    case "lock":
      return lockSummary(line.lock);
    case "close": {
      let said: string;
      if (line.pick) {
        said =
          line.outcome === "converged"
            ? `Everyone's on board: going with ${line.pick}`
            : `Couldn't get everyone there · best was ${line.pick}`;
      } else {
        said = isSuccess(line.outcome)
          ? `${line.protocol} done · ${line.steps} step${line.steps === 1 ? "" : "s"}`
          : `${line.protocol} ${line.outcome} · ${line.reason}`;
      }
      if (line.memory) return `${said} · saved as ${line.memory}`;
      if (line.memory === null) return `${said} · could not be saved`;
      return said;
    }
  }
}

function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Where a count stands, in plain words: "Round 1: 4 new points, 4 in all". */
export function tallySummary(tally: TallyRecord): string {
  if (tally.of === "points") {
    if (tally.outcome === "empty") return "Nobody gave any points";
    if (tally.capped) return `Points were still coming when the rounds ran out: ${tally.points} in all`;
    if (tally.outcome === "settled") return `Nobody added anything new: ${count(tally.points, "point")}`;
    return `Round ${tally.round}: ${count(tally.added, "new point")}, ${tally.points} in all`;
  }
  const words = tally.contested.join(", ");
  if (tally.outcome === "contested") {
    const asked = tally.asked?.length ? `. Asking ${tally.asked.join(", ")} again` : "";
    return `Words used in different senses: ${words}${asked}`;
  }
  return tally.contested.length
    ? `Still used in different senses: ${words}`
    : "No word used in different senses";
}

/** What the shared summary holds: "5 points, 1 stated by more than one person, …". */
export function lockSummary(lock: LockRecord): string {
  if (lock.outcome === "empty") return "Nothing to put in a shared summary";
  const parts = [count(lock.points, "point"), `${lock.shared} stated by more than one person`];
  if (lock.contested) parts.push(count(lock.contested, "word used in different senses", "words used in different senses"));
  if (lock.checks) parts.push(count(lock.checks, "check"));
  if (lock.flagged) parts.push(count(lock.flagged, "open item"));
  const quiet = lock.quiet.length ? ` · no answer from ${lock.quiet.join(", ")}` : "";
  return `Shared summary: ${parts.join(", ")}${quiet}`;
}

/** Where a pick stands, in plain words: "B, everyone at 70+" or "B, @finance at 55". */
export function pickSummary(record: PickRecord): string {
  if (!record.pick) return "nothing to pick yet";
  if (record.outcome === "feasible") return `${record.pick}, everyone at ${record.threshold}+`;
  const short = Object.entries(record.ratings)
    .filter(([, r]) => r < record.threshold)
    .sort((a, b) => a[1] - b[1])
    .map(([h, r]) => `@${h} at ${r}`);
  if (record.missing.length) short.push(`no rating from ${record.missing.map((h) => `@${h}`).join(", ")}`);
  return `${record.pick}, ${short.join("; ") || "short of the bar"}`;
}
