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

/** What each of Concord's and Accord's steps has the members doing, as a word
 *  for a run's live line. */
const STEP_DOING: Record<string, string> = {
  anchor: "anchoring",
  propose: "proposing",
  score: "scoring",
  rescore: "scoring",
  repair: "fixing",
  terms: "naming terms",
  frame: "framing",
  more: "framing",
  ground: "defining terms",
  restate: "clarifying",
};

/** Where a run in a thread stands, for a line about it outside the thread. */
export interface RunProgress {
  protocol: string;
  members: string[];
  /** Still walking. */
  open: boolean;
  /** The step being asked, said as what the members are doing, and how many
   *  of those asked have answered. Null between steps or once it's closed. */
  doing: { what: string; asked: number; answered: number } | null;
  /** The last shared summary, for Accord's counts. */
  lock: LockRecord | null;
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
      run = { protocol: line.protocol, members: line.members, open: true, doing: null, lock: null };
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
    } else if (line?.event === "lock") {
      run.lock = line.lock;
    } else if (line?.event === "close") {
      run.open = false;
      step = null;
    } else if (line) {
      // A pick or a count ends the step it read.
      step = null;
      asked = new Set();
    } else if (ev.chat && asked.has(ev.sender)) {
      answered.add(ev.sender);
    }
  }
  if (run && run.open && step && asked.size) {
    run.doing = { what: STEP_DOING[step] ?? step, asked: asked.size, answered: answered.size };
  }
  return run;
}

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

/** One member's standing on an option: placed 0-1 between its bad outcome
 *  and its ideal, and why. */
export interface Standing {
  member: string;
  placed: number | undefined;
  why: string;
}

/** Every member's standing on `label`, least satisfied last. */
export function standings(record: PickRecord, label: string): Standing[] {
  return record.cast
    .map((member) => ({
      member,
      placed: placedOf(record, label, member),
      why: record.reasons?.[label]?.[member] ?? "",
    }))
    .sort((a, b) => (b.placed ?? -1) - (a.placed ?? -1));
}

/** The member least satisfied with the pick, and how far toward its ideal. */
export function leastSatisfied(record: PickRecord): { member: string; placed: number } | null {
  if (!record.pick) return null;
  const rated = standings(record, record.pick).filter((s) => s.placed !== undefined);
  const last = rated[rated.length - 1];
  return last ? { member: last.member, placed: last.placed! } : null;
}

/** "81%": a placed rating, for a reader. */
export function percent(placed: number): string {
  return `${Math.round(placed * 100)}%`;
}

/**
 * Each member's ratings, by the reply they gave them in: a reply to a score
 * step gets that member's row of the pick that follows it. Read from the
 * conductor's own lines (whom each turn asked, and the pick's table), never
 * from the reply's text. A reply that carries its own (`ReplyRecord`) is drawn
 * from that instead, so it isn't here.
 */
export function ratingsByReply(
  events: { id: string; sender: string; conductor: ConductorLine | null; chat: boolean }[],
): Map<string, { record: PickRecord; member: string }> {
  const out = new Map<string, { record: PickRecord; member: string }>();
  // Replies to a score step waiting for the pick that reads them.
  let waiting: { id: string; member: string }[] = [];
  // Members asked to score whose answer hasn't come yet. The answer is the
  // first thing they say after the turn that asked them; anything else they
  // say before the pick isn't it. A second asking is a turn of its own, so
  // its answer replaces the first.
  const owed = new Set<string>();
  for (const ev of events) {
    const line = ev.conductor;
    if (line?.event === "turn") {
      if (line.step === "score" || line.step === "rescore") owed.add(line.to);
      else owed.delete(line.to);
      continue;
    }
    if (line?.event === "select") {
      for (const w of waiting) out.set(w.id, { record: line.select, member: w.member });
      waiting = [];
      owed.clear();
      continue;
    }
    if (line || !ev.chat || !owed.has(ev.sender)) continue;
    owed.delete(ev.sender);
    waiting = waiting.filter((w) => w.member !== ev.sender);
    waiting.push({ id: ev.id, member: ev.sender });
  }
  return out;
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
      const said = stepSentence(line.protocol, line.step, [line.to]);
      if (said) return `${said}${line.again ? " (asked again)" : ""}`;
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
      return line.select.pick ? `Picked ${pickSummary(line.select)}` : `${line.step}: ${pickSummary(line.select)}`;
    case "tally":
      return tallySummary(line.tally);
    case "lock":
      return lockSummary(line.lock);
    case "close": {
      let said: string;
      if (line.pick) {
        said =
          line.outcome === "converged"
            ? `Picked ${line.pick}`
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

/** How many of an option's first words make its name. */
const NAME_WORDS = 5;

/** The words of a text's first sentence or clause, brackets dropped, and
 *  whether that is the whole text. */
function firstWords(text: string): { words: string[]; whole: boolean } {
  const trimmed = text.trim();
  const first = trimmed.split(/(?<=[.;:])\s/)[0].replace(/[.;:]+$/, "");
  return {
    words: first.replace(/[()[\]]/g, "").split(/\s+/).filter(Boolean),
    whole: first === trimmed.replace(/\.+$/, ""),
  };
}

/** An option's name, for a reader who sees only its letter: a few words of
 *  its first sentence or clause, with `…` where it's cut. `skip` starts past
 *  words other options share. The hub names options the same way in the lines
 *  members fill in. */
export function shortName(text: string, skip = 0): string {
  const { words, whole } = firstWords(text);
  const from = skip >= words.length ? 0 : skip;
  const cut = words.slice(from, from + NAME_WORDS);
  const head = from ? "…" : "";
  const tail = whole && from + cut.length === words.length ? "" : "…";
  return head + cut.join(" ").replace(/,$/, "") + tail;
}

/** `{label: name}` for options, each name different from the others where
 *  the texts allow: options whose first words are the same are named by the
 *  words after the ones they share. The hub names them the same way. */
export function optionNames(options: { label: string; text: string }[]): Record<string, string> {
  const first = Object.fromEntries(options.map((o) => [o.label, shortName(o.text)]));
  const names = { ...first };
  const norm = (text: string) => firstWords(text).words.map((w) => w.replace(/[,;]+$/, "").toLowerCase());
  for (const o of options) {
    const twins = options.filter((t) => t.label !== o.label && first[t.label] === first[o.label]);
    if (!twins.length) continue;
    const words = norm(o.text);
    let shared = 0;
    for (const t of twins) {
      const other = norm(t.text);
      let same = 0;
      while (same < Math.min(words.length, other.length) && words[same] === other[same]) same++;
      shared = Math.max(shared, same);
    }
    names[o.label] = shortName(o.text, shared);
  }
  return names;
}

/** `D (Hold a gift order until…)`: a letter a reader can follow, by its name
 *  among `names` when given (`optionNames`). */
export function named(label: string, text: string, names?: Record<string, string>): string {
  const name = names?.[label] ?? (text ? shortName(text) : "");
  return name ? `${label} (${name})` : label;
}

/** Concord's and accord's steps as what the members are doing, by step id:
 *  the verb for one member, then for several. */
const STEP_SAID: Record<string, Record<string, [string, string]>> = {
  concord: {
    anchor: ["rates the two ends: nothing agreed, and their own pick", "rate the two ends: nothing agreed, and their own pick"],
    propose: ["proposes an option, with why", "propose an option each, with why"],
    score: ["rates every option, with reasons", "rate every option, with reasons"],
    repair: ["proposes a fix that answers the objections", "propose a fix that answers the objections"],
    rescore: ["rates the new option", "rate the new option"],
  },
  accord: {
    terms: ["names the key terms", "name the key terms"],
    frame: ["says what the task is", "say what the task is"],
    more: ["adds what's missing", "add what's missing"],
    ground: ["defines the key terms and takes on checks", "define the key terms and take on checks"],
    restate: ["restates the term, with an example", "restate the term they differ on, with an example"],
  },
};

/** What `count` members are doing at a step ("rate the new option"), or
 *  `null` for a step with no wording here. */
export function stepVerb(protocol: string, step: string, count: number): string | null {
  const said = STEP_SAID[protocol]?.[step];
  if (!said || count === 0) return null;
  return count === 1 ? said[0] : said[1];
}

/** What a step's turn is, said as what the members are doing ("finance and
 *  legal rate the new option"), or `null` for a step with no wording here. */
export function stepSentence(protocol: string, step: string, who: string[]): string | null {
  const verb = stepVerb(protocol, step, who.length);
  if (!verb) return null;
  const names = who.length === 1 ? who[0] : `${who.slice(0, -1).join(", ")} and ${who[who.length - 1]}`;
  return `${names} ${verb}`;
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

/** Where a pick stands, in words: "B (10% off), least satisfied: finance at 81%", or
 *  who is short and why: "B (10% off): finance is short of the bar, because margin drops". */
export function pickSummary(record: PickRecord): string {
  if (!record.pick) return "nothing to pick yet";
  const pick = named(record.pick, record.text, optionNames(record.options));
  if (record.outcome === "feasible") {
    const least = leastSatisfied(record);
    return least ? `${pick}, least satisfied: ${least.member} at ${percent(least.placed)}` : pick;
  }
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
  return `${pick}: ${short.join("; ") || "short of the bar"}`;
}
