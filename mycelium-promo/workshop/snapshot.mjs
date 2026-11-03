#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Take the workshop's room from a real hub, for the mock to replay
 * (`src/mocks/workshop.ts`): the run the multiplayer videos show, and the
 * earlier runs that make the room look lived in.
 *
 *   node mycelium-promo/workshop/snapshot.mjs [hub URL]   # default http://127.0.0.1:8000
 *   node mycelium-promo/workshop/snapshot.mjs --concord-from showcase-s2
 *
 * Every word is the hub's, as recorded. What changes: the rooms become one
 * room, `release-planning`; the person who ran them becomes the cast's people,
 * one per step (`SENDERS`); and the history rooms are moved into the past so
 * the run is the room's newest work. A message that carries an email address
 * stops the snapshot rather than being written.
 */

import { writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, "../../mycelium-frontend/src/mocks/workshop/release-planning.json");
const args = process.argv.slice(2);
const flag = (name) => {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : undefined;
};
const HUB = (args.find((a, i) => !a.startsWith("--") && !args[i - 1]?.startsWith("--")) ?? "http://127.0.0.1:8000").replace(/\/$/, "");
/** A separate run for the Concord take, when its own run is where Concord
 *  went best (`--concord-from showcase-s2`). */
const CONCORD_FROM = flag("--concord-from");

/** The room every source becomes. */
const ROOM = "release-planning";

/** The run the takes replay, and the room behind it: an earlier release
 *  decision, so the room has work in it already. (`demo-dryrun-d1` decided
 *  the same task about Mycelium's own features, so only one of the two.) */
const RUN = "showcase-s1";
const HISTORY = ["demo-dryrun-d2"];

/** Who said what the person running the harness said, by what it says. The
 *  first match wins; anything unmatched is Julia's. */
const SENDERS = [
  { match: /^@conductor accord/, as: "jodee" },
  { match: /^@conductor concord/, as: "marc" },
];
const RUNNER_HANDLE = "lead";
const DEFAULT_PERSON = "julia";

const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/;

async function get(path) {
  const res = await fetch(`${HUB}/api${path}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

/** A room's messages, oldest first. */
async function messages(room) {
  const all = [];
  for (let offset = 0; ; offset += 500) {
    const page = await get(`/rooms/${room}/messages?limit=500&offset=${offset}`);
    const list = Array.isArray(page) ? page : (page.messages ?? []);
    all.push(...list);
    if (list.length < 500) break;
  }
  return all.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

async function memories(room) {
  const list = await get(`/rooms/${room}/memory?limit=1000`);
  return Array.isArray(list) ? list : (list.memories ?? []);
}

async function episodes(room) {
  const res = await get(`/rooms/${room}/episodes`);
  return res.episodes ?? [];
}

/** Every mention of a source room's name, in any string, made the room's. */
function rename(value, from) {
  return JSON.parse(JSON.stringify(value).split(from).join(ROOM));
}

function person(content) {
  return SENDERS.find((s) => s.match.test(content))?.as ?? DEFAULT_PERSON;
}

/** One source room, as the room's: its senders cast, its times kept. */
async function take(room) {
  const [msgs, mems, eps] = await Promise.all([messages(room), memories(room), episodes(room)]);
  const cast = msgs.map((m) =>
    m.sender_handle === RUNNER_HANDLE ? { ...m, sender_handle: person(m.content ?? "") } : m,
  );
  const memoryOwner = (m) => (m.created_by === RUNNER_HANDLE ? DEFAULT_PERSON : m.created_by);
  const castMems = mems.map((m) => ({
    ...m,
    created_by: memoryOwner(m),
    updated_by: m.updated_by === RUNNER_HANDLE ? DEFAULT_PERSON : m.updated_by,
  }));
  return castRunner(rename({ room, messages: cast, memories: castMems, episodes: eps }, room));
}

/** Anything else that names the harness's handle, as Julia: a memory notice's
 *  `updated_by`, a manifest's `owner: lead`, an agent writing "@lead" or "@~lead". */
function castRunner(value) {
  const text = JSON.stringify(value)
    .split(`"${RUNNER_HANDLE}"`)
    .join(`"${DEFAULT_PERSON}"`)
    .replace(new RegExp(`(@[~!]?|owner: )${RUNNER_HANDLE}\\b`, "g"), `$1${DEFAULT_PERSON}`)
    .replace(new RegExp(`\\\\"${RUNNER_HANDLE}\\\\"`, "g"), `\\"${DEFAULT_PERSON}\\"`);
  return JSON.parse(text);
}

/** The machines the hub knows, by id and by label: what a snapshot must not name. */
const MACHINES = await get("/runners")
  .then((r) => (Array.isArray(r) ? r : (r.runners ?? [])).flatMap((m) => [m.id, m.label]).filter(Boolean))
  .catch(() => []);
/** Where the run's agents really ran, as the cast's machine. */
const CAST_MACHINE = "julias-mbp";
const HOME = /\/(?:Users|home)\/[^/"\\\s]+/g;

/** Where the run happened, out of it: a home folder becomes `~`, a real
 *  machine becomes the cast's. */
function scrub(value) {
  let text = JSON.stringify(value).replace(HOME, "~");
  for (const id of MACHINES) text = text.split(id).join(CAST_MACHINE);
  return JSON.parse(text);
}

/** An agent's manifest without the lines that say where it ran. */
function bareManifest(m) {
  if (!m.key.startsWith("agents/")) return m;
  const strip = (s) => s.replace(/^(runner|cwd):.*\n?/gm, "");
  if (typeof m.value === "string") return { ...m, value: strip(m.value) };
  if (m.value && typeof m.value.text === "string") return { ...m, value: { ...m.value, text: strip(m.value.text) } };
  return m;
}

const run = await take(RUN);
const history = [];
for (const room of HISTORY) history.push(await take(room));

/** Only what the mock reads: the rest of each record is the hub's bookkeeping. */
const KEEP = {
  message: ["id", "sender_handle", "message_type", "content", "created_at", "recipient_handle", "episode", "metadata"],
  memory: ["key", "value", "meta", "created_by", "updated_by", "version", "created_at", "updated_at", "episode"],
};
const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
/** A conductor's turn is drawn from its line; the prompt behind it stays shut
 *  in every take, so only its first line is kept (the snapshot has a size cap). */
const trimTurn = (m) =>
  m.metadata?.conductor?.event === "turn" ? { ...m, content: (m.content ?? "").split("\n")[0] } : m;
const slim = (s) => ({
  room: s.room,
  messages: s.messages.map((m) => trimTurn(pick(m, KEEP.message))),
  // A run's record (`log/episodes/…`) is what the episodes are read from; the
  // takes read the episodes.
  memories: s.memories.filter((m) => !m.key.startsWith("log/")).map((m) => bareManifest(pick(m, KEEP.memory))),
  episodes: s.episodes,
});

const concordRun = CONCORD_FROM ? slim(await take(CONCORD_FROM)) : undefined;
const snapshot = scrub({ room: ROOM, run: slim(run), concordRun, history: history.map(slim) });
const text = JSON.stringify(snapshot);

// What must never be written: an email address, a home folder, a real machine,
// or the harness's own handle where a person or owner would show.
const checks = [
  ["an email address", EMAIL.exec(text.replace(/@(conductor|~?[a-z][\w-]*)\b/g, ""))?.[0]],
  ["a home folder", /\/(?:Users|home)\//.exec(text)?.[0]],
  ["a machine id", MACHINES.find((id) => text.includes(id))],
  ["the harness's handle", new RegExp(`(@[~!]?|owner: |")${RUNNER_HANDLE}\\b`).exec(text)?.[0]],
];
for (const [what, found] of checks) {
  if (found) {
    console.error(`refusing: ${what} is in the snapshot (${found})`);
    process.exit(1);
  }
}
writeFileSync(OUT, `${text}\n`);
console.log(`${OUT}: ${run.messages.length} run messages, ${history.map((h) => h.messages.length).join(" + ")} history`);
