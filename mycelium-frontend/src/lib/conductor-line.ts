// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A conductor post carries a structured line beside its prose
// (`conductor.LINE_KEY` on the hub): the prose is what the members read, the
// line is what a thread draws instead, so a run reads as its steps rather than
// as the prompts behind them. The line arrives two ways, like every message: on
// the live stream inside the message's payload, and on a reload in the
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
  outcome: "feasible" | "infeasible" | "stuck" | "nothing";
  pick: string | null;
  text: string;
  /** The bar, 0-100: how far from each member's bad outcome to its ideal the
   *  pick has to be. */
  threshold: number;
  /** Each option, with why the members who proposed it did. */
  options: { label: string; text: string; authors: string[]; why?: Record<string, string> }[];
  /** `{letter: {member: rating}}`, on each member's own scale; a member who
   *  gave none is absent. */
  table: Record<string, Record<string, number>>;
  /** `{letter: {member: 0-1}}`: each rating placed between the member's bad
   *  and ideal outcomes. Absent on records made before ratings were placed. */
  placed?: Record<string, Record<string, number>>;
  /** `{letter: {member: why}}`, the reason each rating came with. */
  reasons?: Record<string, Record<string, string>>;
  cast: string[];
  ratings: Record<string, number>;
  lowest: number | null;
  missing: string[];
  least_happy: string | null;
  /** The members short of the bar on the pick, least happy first, with why. */
  short?: { member: string; placed: number; why: string }[];
}

/** From here a rating reads as close to the member's ideal. */
const NEAR_IDEAL = 0.9;

/** Where `member`'s rating of option `label` stands, 0-1: placed between its
 *  own bad and ideal outcomes, or out of 100 on a record from before that. */
export function placedOf(record: PickRecord, label: string, member: string): number | undefined {
  const at = record.placed?.[label]?.[member];
  if (at !== undefined) return at;
  const raw = record.table[label]?.[member];
  return raw === undefined ? undefined : Math.max(0, Math.min(1, raw / 100));
}

/** What a placed rating means against the bar (both 0-1), in words. */
export function verdict(value: number | undefined, bar: number): string {
  if (value === undefined) return "gave no rating";
  if (value <= 0) return "no better than the bad outcome";
  if (value < bar) return "short of the bar";
  if (value >= NEAR_IDEAL) return "close to the ideal";
  return "meets the bar";
}

/** `text` as it reads after a comma: its first letter lowered, unless the
 *  first word is "I" or reads as a name or an acronym (`SLA`, `iOS`). */
export function midSentence(text: string): string {
  const first = text.trim().split(/\s+/)[0] ?? "";
  const keep = first === "I" || first.startsWith("I'") || first.startsWith("I’") || /[A-Z]/.test(first.slice(1));
  return keep || !text ? text : text[0].toLowerCase() + text.slice(1);
}

function because(why: string | undefined): string {
  return why ? `, because ${midSentence(why)}` : "";
}

/** Each member's view of one option: what their rating means, and why. */
export function views(
  record: PickRecord,
  label: string,
): { member: string; verdict: string; why: string; short: boolean }[] {
  const bar = record.threshold / 100;
  return record.cast.map((member) => {
    const at = placedOf(record, label, member);
    return {
      member,
      verdict: verdict(at, bar),
      why: record.reasons?.[label]?.[member] ?? "",
      short: at !== undefined && at < bar,
    };
  });
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
            ? `Everyone meets the bar: going with ${line.pick}`
            : line.outcome === "resolved"
              ? `Best found: ${line.pick}, below the bar for some`
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

/** Where a pick stands, in words: "B: everyone meets the bar", or who is
 *  short and why: "B: finance is short of the bar, because margin drops". */
export function pickSummary(record: PickRecord): string {
  if (!record.pick) return "nothing to pick yet";
  if (record.outcome === "feasible") return `${record.pick}: everyone meets the bar`;
  const short = (
    record.short ??
    views(record, record.pick)
      .filter((v) => v.short)
      .map((v) => ({ member: v.member, placed: placedOf(record, record.pick!, v.member) ?? 0, why: v.why }))
      .sort((a, b) => a.placed - b.placed)
  ).map((s) =>
    s.placed > 0
      ? `${s.member} is short of the bar${because(s.why)}`
      : `${s.member} finds it no better than the bad outcome${because(s.why)}`,
  );
  if (record.missing.length) short.push(`no rating from ${record.missing.join(", ")}`);
  return `${record.pick}: ${short.join("; ") || "short of the bar"}`;
}
