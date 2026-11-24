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
  | {
      event: "close";
      protocol: string;
      outcome: string;
      steps: number;
      reason: string;
    };

/** Where a run in a thread stands, for a line about it outside the thread. */
export interface RunProgress {
  protocol: string;
  members: string[];
  /** Still walking. */
  open: boolean;
  /** The step being asked and how many of those asked have answered. Null
   *  between steps or once it's closed. */
  doing: { what: string; asked: number; answered: number } | null;
}

/** The latest run in one thread's events, in order, or `null` when none ran. */
export function runProgress(
  events: { sender: string; conductor: ConductorLine | null; chat: boolean }[],
): RunProgress | null {
  let run: RunProgress | null = null;
  let asked = new Set<string>();
  let answered = new Set<string>();
  let step: string | null = null;
  for (const ev of events) {
    const line = ev.conductor;
    if (line?.event === "open") {
      run = { protocol: line.protocol, members: line.members, open: true, doing: null };
      asked = new Set();
      answered = new Set();
      step = null;
      continue;
    }
    if (!run) continue;
    if (line?.event === "turn") {
      if (line.step !== step) {
        step = line.step;
        asked = new Set();
        answered = new Set();
      }
      asked.add(line.to);
    } else if (line?.event === "close") {
      run.open = false;
      step = null;
    } else if (!line && ev.chat && asked.has(ev.sender)) {
      answered.add(ev.sender);
    }
  }
  if (run && run.open && step && asked.size) {
    run.doing = { what: step, asked: asked.size, answered: answered.size };
  }
  return run;
}

/** A run that resolved reads as success; one that was rejected, as a failure. */
export function isSuccess(outcome: string): boolean {
  return outcome === "resolved";
}

const EVENTS = new Set(["open", "turn", "edge", "close"]);

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
  return asLine(payloadData(message.content)?.conductor);
}

function payloadData(content: unknown): Record<string, unknown> | null {
  if (typeof content === "string") {
    if (!content.startsWith("{")) return null;
    try {
      content = JSON.parse(content);
    } catch {
      return null;
    }
  }
  return (
    (content as { l9?: { payload?: { data?: Record<string, unknown> } } } | null)?.l9?.payload?.data ?? null
  );
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
      const again = line.again ? " (asked again)" : "";
      return `${line.step} → ${line.to}${again} · turn ${line.turn} of ${line.cap}${round}`;
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
    case "close":
      return isSuccess(line.outcome)
        ? `${line.protocol} done · ${line.steps} step${line.steps === 1 ? "" : "s"}`
        : `${line.protocol} ${line.outcome} · ${line.reason}`;
  }
}

/**
 * A step put to several members at once posts one turn per member, back to
 * back. A thread draws the run as one row: `{id: members}` for the first turn
 * of each run of turns at the same step and turn number, and `{id: null}` for
 * the turns that run folds in. Turns put one at a time are interleaved with
 * replies, so each stays its own row.
 */
export function turnRuns(events: { id: string; conductor: ConductorLine | null }[]): Map<string, string[] | null> {
  const runs = new Map<string, string[] | null>();
  let head: { id: string; key: string; who: string[] } | null = null;
  for (const ev of events) {
    const line = ev.conductor;
    if (line?.event !== "turn") {
      head = null;
      continue;
    }
    const key = `${line.protocol}\u0000${line.step}\u0000${line.turn}\u0000${line.round ?? 0}\u0000${line.again ? 1 : 0}`;
    if (head && head.key === key) {
      head.who.push(line.to);
      runs.set(ev.id, null);
      continue;
    }
    head = { id: ev.id, key, who: [line.to] };
    runs.set(ev.id, head.who);
  }
  return runs;
}
