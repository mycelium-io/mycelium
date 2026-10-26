// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The workshop scenario: a replay of a real run, for the videos the workshop's
 * multiplayer section shows.
 *
 * `MYCELIUM_UI_MOCK_SCENARIO=workshop:<take>` adds the `release-planning` room,
 * built from a snapshot of a real hub (`workshop/release-planning.json`, taken
 * by `mycelium-promo/workshop/snapshot.mjs`), on a team's hub with its other
 * rooms (`workshop-room.ts`). Three people share it, each with an agent on
 * their own laptop. The task's thread opens on its description alone; when a
 * person sends the take's opening message, that step's messages play back in
 * the order they were said, word for word, at reading speed.
 *
 * `mycelium-promo/workshop/record.mjs` records a take per server.
 */

import type { EpisodeSummary } from "@/lib/api";
import { once, nowIso, sleep } from "./director";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { liveEpisode, memoryChangedFrame, pingFrame, publish, respondingFrame } from "./live";
import taken from "./workshop/release-planning.json";
import { WORKSHOP_TEAMMATES, liveIn, workshopOtherRooms } from "./workshop-room";

export { WORKSHOP_HUB_URL, WORKSHOP_TEAMMATES, workshopFolders } from "./workshop-room";

/** A message, memory and episode as the hub served them when the snapshot was taken. */
interface SnapMessage {
  id: string;
  sender_handle: string;
  message_type: string;
  content: string | null;
  created_at: string;
  recipient_handle?: string | null;
  episode?: string | null;
  metadata?: Record<string, unknown> | null;
}
interface SnapMemory {
  key: string;
  value: unknown;
  meta?: Record<string, unknown> | null;
  created_by: string;
  updated_by?: string | null;
  version?: number;
  created_at: string;
  updated_at: string;
  episode?: string | null;
}
interface Source {
  room: string;
  messages: SnapMessage[];
  memories: SnapMemory[];
  episodes: EpisodeSummary[];
}
interface Snapshot {
  room: string;
  run: Source;
  /** A run of its own for the Concord take, when there is one. */
  concordRun?: Source;
  history: Source[];
}

const snapshot = taken as unknown as Snapshot;

/** The run a take replays. */
function runOf(take: WorkshopTake): Source {
  return take === "concord" && snapshot.concordRun ? snapshot.concordRun : snapshot.run;
}

export const WORKSHOP_TAKES = ["multiplayer", "accord", "concord"] as const;
export type WorkshopTake = (typeof WORKSHOP_TAKES)[number];

/** The take this server plays, when the scenario is the workshop's. */
export function workshopTake(): WorkshopTake | null {
  const m = /^workshop:([\w-]+)$/.exec((process.env.MYCELIUM_UI_MOCK_SCENARIO ?? "").toLowerCase());
  return m && (WORKSHOP_TAKES as readonly string[]).includes(m[1]) ? (m[1] as WorkshopTake) : null;
}

export const isWorkshopScenario = (): boolean => workshopTake() !== null;

export const WORKSHOP_ROOM = "release-planning";

/** The people in the room, each with the agent on their own laptop. */
export const WORKSHOP_CAST = [
  { handle: "julia", name: "Julia Valenti", agent: "eng", machine: "julias-mbp" },
  { handle: "jodee", name: "Jodee Varney", agent: "product", machine: "jodees-mbp" },
  { handle: "marc", name: "Marc Scibelli", agent: "design", machine: "marcs-mbp" },
] as const;


const BOOT = Date.now();
const PEOPLE = new Set<string>(WORKSHOP_CAST.map((c) => c.handle));

/** The step each take plays: its opening human message, matched by what it says. */
const STEP_OPENS: Record<WorkshopTake, RegExp> = {
  multiplayer: /^@eng @product @design /,
  accord: /^@conductor accord\b/,
  concord: /^@conductor concord\b/,
};

/**
 * Where a take ends early: the message it stops after, and the few lines a
 * person says there. The agents' words are only ever the run's; a person's
 * line here is written for the video (the run had one person in it).
 */
const ENDS: Partial<Record<WorkshopTake, { after: RegExp; sender: string; line: string }>> = {
  multiplayer: {
    after: /^\*\*Product accepts @~eng's timeline\./,
    sender: "jodee",
    line: "@julia That's my agent's view, and I'm with it. I'll run Accord next so we're all deciding the same thing.",
  },
};

/** Takes that play a step's first run when it was run more than once. Concord
 *  was rerun with a higher bar, and the first run is the one the video shows. */
const PLAY_FIRST = new Set<WorkshopTake>(["concord"]);

/**
 * The run's messages: before the take's step, and the step itself. A step run
 * more than once plays its last run (or its first, `PLAY_FIRST`), and the room
 * opens as it stood before the first, so another attempt isn't in it.
 * `cutoff` is when the first began: what the run wrote after it waits.
 */
function cut(take: WorkshopTake): { before: SnapMessage[]; step: SnapMessage[]; cutoff: number } {
  const msgs = runOf(take).messages;
  const opensAt = (re: RegExp) =>
    msgs.flatMap((m, i) => (PEOPLE.has(m.sender_handle) && re.test(m.content ?? "") ? [i] : []));
  const mine = opensAt(STEP_OPENS[take]);
  if (mine.length === 0) return { before: msgs, step: [], cutoff: Infinity };
  const first = mine[0];
  const at = PLAY_FIRST.has(take) ? first : mine.at(-1)!;
  const all = (Object.keys(STEP_OPENS) as WorkshopTake[]).flatMap((t) => opensAt(STEP_OPENS[t]));
  let next = all.filter((i) => i > at).sort((a, b) => a - b)[0] ?? msgs.length;
  const end = ENDS[take];
  if (end) {
    const stop = msgs.findIndex((m, i) => i > at && end.after.test(m.content ?? ""));
    if (stop >= 0) next = Math.min(next, stop + 1);
  }
  return { before: msgs.slice(0, first), step: msgs.slice(at, next), cutoff: ms(msgs[first].created_at) };
}

const ms = (iso: string): number => Date.parse(iso);

/** Times moved so `last` lands `ago` ms before now, keeping every gap. */
function shifter(lastIso: string | undefined, ago: number): (iso: string) => string {
  const delta = lastIso ? BOOT - ago - ms(lastIso) : 0;
  return (iso: string) => new Date(ms(iso) + delta).toISOString();
}

function asMessage(m: SnapMessage, at: string): MockMessage {
  return {
    id: m.id,
    sender_handle: m.sender_handle,
    message_type: m.message_type,
    content: m.content ?? "",
    created_at: at,
    recipient_handle: m.recipient_handle,
    episode: m.episode,
    metadata: (m.metadata as Record<string, unknown> | null) ?? null,
  };
}

function asMemory(m: Source["memories"][number], at: (iso: string) => string): MockMemory {
  const value = typeof m.value === "object" && m.value && "text" in m.value ? String(m.value.text) : String(m.value);
  return {
    key: m.key,
    value,
    content_text: value,
    meta: (m.meta as Record<string, unknown> | null) ?? null,
    created_by: m.created_by,
    updated_by: m.updated_by ?? m.created_by,
    version: m.version ?? 1,
    updated_at: at(m.updated_at),
    episode: (m as { episode?: string | null }).episode ?? undefined,
  };
}

/** What each agent speaks for, from the run's own brief for it. */
const ROLE: Record<string, string> = {
  eng: "Speaks for engineering: what's built, what's risky and what it costs.",
  product: "Speaks for product: what customers asked for and what sales has promised.",
  design: "Speaks for design: what people see and feel while offline, and what needs testing with real users.",
};

function manifestOf(c: (typeof WORKSHOP_CAST)[number]): MockMemory {
  const value = `adapter: claude_code\ndescription: "${ROLE[c.agent]}"\nowner: ${c.handle}\n`;
  return {
    key: `agents/${c.agent}`,
    value,
    content_text: value,
    meta: null,
    created_by: c.handle,
    updated_by: c.handle,
    version: 1,
    updated_at: new Date(BOOT - 3 * 3_600_000).toISOString(),
  };
}

function shiftEpisode(e: EpisodeSummary, at: (iso: string) => string): EpisodeSummary {
  return {
    ...e,
    updated_at: at(e.updated_at),
    trace: e.trace?.map((t) => (t.at ? { ...t, at: at(t.at) } : t)),
  };
}

/** The room as it stood just before the take's step. */
export function workshopRoom(): RoomFixture | null {
  const take = workshopTake();
  if (!take) return null;
  const { before, step, cutoff } = cut(take);
  const history = snapshot.history;
  const lastHistory = history.flatMap((h) => h.messages).at(-1)?.created_at;
  // The earlier work is a day old; the run's own start, minutes.
  const past = shifter(lastHistory, 26 * 3_600_000);
  const run = shifter(before.at(-1)?.created_at ?? step[0]?.created_at, 90_000);
  const stepStart = cutoff;

  // Each agent's manifest names its person; the snapshot's name whoever ran it.
  const cast = new Set<string>(WORKSHOP_CAST.map((c) => `agents/${c.agent}`));
  const byKey = new Map<string, MockMemory>();
  for (const m of [
    ...history.flatMap((h) => h.memories.map((x) => asMemory(x, past))),
    ...runOf(take).memories.filter((x) => ms(x.created_at) < stepStart).map((x) => asMemory(x, run)),
  ]) {
    if (cast.has(m.key)) continue;
    // An engine's manifest says `owner: null`, which would read as a person.
    if (m.key.startsWith("agents/") && typeof m.value === "string") m.value = m.value.replace(/^owner:\s*null\s*$/m, "");
    byKey.set(m.key, m);
  }
  const memories = [...byKey.values(), ...WORKSHOP_CAST.map(manifestOf)];
  // Each take opens on the task's description alone: what the run said in the
  // thread before the step (and the flows it ran) belongs to an earlier take.
  // The room's notices stay.
  const messages = [
    ...history.flatMap((h) => h.messages.map((m) => asMessage(m, past(m.created_at)))),
    ...before.filter((m) => m.message_type !== "broadcast").map((m) => asMessage(m, run(m.created_at))),
  ];
  const episodes = history.flatMap((h) => (h.episodes as EpisodeSummary[]).map((e) => shiftEpisode(e, past)));
  const fx: RoomFixture = {
    room: {
      id: 9101,
      name: WORKSHOP_ROOM,
      is_public: false,
      is_persistent: true,
      owner: WORKSHOP_CAST[0].handle,
      members: WORKSHOP_PEOPLE,
      created_at: new Date(BOOT - 45 * 24 * 3_600_000).toISOString(),
    },
    memories,
    messages,
    episodes,
    episodeDetails: {},
  };
  // The team's two weeks around the run, with its agents at work. Multiplayer
  // is about three laptops, so there the cast's agents read by the machine
  // each runs on, which the rail names only for an agent that isn't active.
  liveIn(
    fx,
    take === "multiplayer"
      ? []
      : [
          { handle: "eng", status: "working" },
          { handle: "product", status: "working" },
          { handle: "design", status: "idle" },
        ],
  );
  return fx;
}

/** Everyone on the team, the cast first. */
export const WORKSHOP_PEOPLE: string[] = [...WORKSHOP_CAST.map((c) => c.handle), ...WORKSHOP_TEAMMATES.map((t) => t.handle)];

/** The hub's other rooms, for the sidebar. */
export function workshopRooms(): Record<string, RoomFixture> {
  return isWorkshopScenario() ? workshopOtherRooms(WORKSHOP_CAST[0].handle, WORKSHOP_PEOPLE) : {};
}

/** Reading speed, not the run's own: an agent's message comes after a beat of
 *  it responding (`think`), then has the screen to itself for `read`, so its
 *  first lines can be read. The conductor's lines and the room's bookkeeping
 *  go by quickly. Only the waiting is shortened, never the reading. */
const PACE: Record<WorkshopTake, { think: number; read: number }> = {
  multiplayer: { think: 1000, read: 3800 },
  accord: { think: 900, read: 3400 },
  concord: { think: 1000, read: 3800 },
};

const isAgentLine = (m: SnapMessage): boolean =>
  m.message_type === "broadcast" && !PEOPLE.has(m.sender_handle) && m.sender_handle !== "conductor";

/** The step's episodes, as they stand at `clock` on the run's own time: a
 *  step is there once it was taken, and the outcome once the run ended.
 *  Episodes that began before `since` aren't the step's (the room has them
 *  already, or they were an earlier attempt). */
function episodesAt(source: Source, clock: number, since: number, at: (iso: string) => string): EpisodeSummary[] {
  return source.episodes.flatMap((e) => {
    const trace = e.trace ?? [];
    const first = trace[0]?.at ? ms(trace[0].at) : Infinity;
    if (first < since || clock < first - 30_000) return [];
    const taken = trace.filter((t) => !t.at || ms(t.at) <= clock);
    const done = trace.at(-1)?.at ? clock >= ms(trace.at(-1)!.at!) : false;
    return [
      shiftEpisode(
        {
          ...e,
          trace: taken,
          outcome: done ? e.outcome : "open",
          current_step: done ? e.current_step : (taken.at(-1)?.next ?? trace[0]?.step ?? null),
        },
        at,
      ),
    ];
  });
}

/** Play the take's step: each message in turn, the episode keeping pace. The
 *  step's opening message was just typed in the app, so it isn't played again. */
async function replay(fx: RoomFixture, take: WorkshopTake): Promise<void> {
  const { step } = cut(take);
  if (step.length === 0) return;
  const { think, read } = PACE[take];
  const live = liveEpisode(WORKSHOP_ROOM);
  // The run's earlier episodes are timed on the replay's clock along with the
  // step's, so the step's stays the newest whatever the server's start time.
  const source = runOf(take);
  const runIds = new Set(source.episodes.map((e) => e.short_id));
  const kept = fx.episodes.filter((e) => !runIds.has(e.short_id));
  const earlier = source.episodes.filter((e) => fx.episodes.some((x) => x.short_id === e.short_id));
  const since = ms(step[0].created_at);
  // What the step wrote, at the time it last wrote it (a rerun rewrites the decision).
  const runMemories = runOf(take).memories.filter((m) => ms(m.updated_at) >= since);
  let shown = new Set<string>();
  let previous = ms(step[0].created_at);
  // The run's clock, mapped onto now: what has played is "now", what hasn't is to come.
  const toNow = (iso: string): string => new Date(Date.now() - (lastPlayed - ms(iso))).toISOString();
  let lastPlayed = previous;
  for (const [i, m] of step.entries()) {
    const agent = isAgentLine(m);
    if (agent) {
      publish(WORKSHOP_ROOM, respondingFrame(m.sender_handle, m.episode ?? null));
      await sleep(think);
    } else {
      await sleep(m.sender_handle === "conductor" ? 450 : 120);
    }
    previous = ms(m.created_at);
    lastPlayed = previous;

    // The opening message is the one just typed: the room already has it.
    if (i > 0 || !PEOPLE.has(m.sender_handle)) {
      const msg: MockMessage = { ...asMessage(m, nowIso()), id: `${m.id}-replay` };
      fx.messages.push(msg);
      publish(WORKSHOP_ROOM, { ...msg, room_name: WORKSHOP_ROOM });
      if (msg.episode && msg.episode !== live && msg.message_type === "broadcast") {
        publish(WORKSHOP_ROOM, pingFrame(WORKSHOP_ROOM, { episode: msg.episode, sender: msg.sender_handle, message: msg.id }));
      }
    }

    // Memories the run wrote by now, and its episodes as they stood.
    for (const mem of runMemories) {
      if (shown.has(mem.key) || ms(mem.updated_at) > previous) continue;
      shown = new Set(shown).add(mem.key);
      const row = asMemory(mem, toNow);
      fx.memories = fx.memories.filter((x) => x.key !== row.key).concat(row);
      publish(WORKSHOP_ROOM, memoryChangedFrame(row.key, row.version, row.updated_by ?? "conductor"));
    }
    // Newest first, as the hub lists them: the thread's flow panel shows the first.
    fx.episodes = [
      ...episodesAt(source, previous, since - 60_000, toNow),
      ...earlier.map((e) => shiftEpisode(e, toNow)),
      ...kept,
    ];
    if (agent) await sleep(read);
  }

  // The person's line the take ends on, a beat after the last agent's.
  const end = ENDS[take];
  const last = step.at(-1);
  if (end && last) {
    await sleep(3200);
    const msg: MockMessage = {
      id: `${WORKSHOP_ROOM}-${take}-end`,
      sender_handle: end.sender,
      message_type: "broadcast",
      content: end.line,
      created_at: nowIso(),
      episode: last.episode ?? null,
    };
    fx.messages.push(msg);
    publish(WORKSHOP_ROOM, { ...msg, room_name: WORKSHOP_ROOM });
  }
}

/** A person sent the take's opening message in the app (typed on screen, as
 *  the run's person did): the step plays from there. */
export function workshopOnMessage(fx: RoomFixture, room: string, m: MockMessage): void {
  const take = workshopTake();
  if (room !== WORKSHOP_ROOM || !take || !PEOPLE.has(m.sender_handle)) return;
  if (!STEP_OPENS[take].test(m.content.trim()) || !once(`workshop:${take}`)) return;
  void replay(fx, take);
}
