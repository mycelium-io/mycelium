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
  | {
      event: "close";
      protocol: string;
      outcome: string;
      steps: number;
      reason: string;
      /** The option a run that picked ended on. */
      pick?: string;
      text?: string;
    };

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

const EVENTS = new Set(["open", "turn", "edge", "select", "close"]);

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
    case "close":
      if (line.pick) {
        return line.outcome === "converged"
          ? `Everyone's on board: going with ${line.pick}`
          : `Couldn't get everyone there · best was ${line.pick}`;
      }
      return isSuccess(line.outcome)
        ? `${line.protocol} done · ${line.steps} step${line.steps === 1 ? "" : "s"}`
        : `${line.protocol} ${line.outcome} · ${line.reason}`;
  }
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
