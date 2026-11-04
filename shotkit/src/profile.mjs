/**
 * `shot profile`: how long an interaction holds the page, measured.
 *
 * The page is brought to its starting state by the flows and `--do` steps, which
 * aren't measured. Then the `--measure` steps run, the clock starts at the first
 * of them, and the page counts as usable once `--until` is met and the main
 * thread has then gone `QUIET_MS` without a stall.
 *
 * A stall is read the same way in every engine: a 10 ms timer in the page notes
 * every gap over `STALL_MS`, which is a stretch the page could not answer a
 * click or a key. WebKit (the engine of a Tauri app on macOS) reports no long
 * tasks, so the timer is what makes the two comparable. In Chromium a CPU
 * profile is taken too, saved as a `.cpuprofile` that DevTools opens, and its
 * self time is summed by function, mapped through the app's source maps when it
 * serves them, so the summary names the code rather than a minified chunk.
 *
 * Runs are separate pages in one browser: a run can't warm the next one's cache
 * unless the measured steps do it themselves (say, switching away and back).
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { runAction, runActions } from "./actions.mjs";

/** A gap longer than this, in ms, is a stall. */
export const STALL_MS = 50;
/** Usable means `--until` is met and then this long passes with no stall. */
export const QUIET_MS = 500;
/** The longest wait for quiet after `--until`, so a page that never settles still reports. */
const QUIET_LIMIT_MS = 10_000;

/** The in-page timer, put in before anything on the page runs. */
function heartbeat() {
  const w = /** @type {any} */ (window);
  w.__shotStalls = [];
  let last = performance.now();
  setInterval(() => {
    const now = performance.now();
    if (now - last > 60) w.__shotStalls.push({ at: last, ms: now - last - 10 });
    last = now;
  }, 10);
}

/**
 * Stalls after `start`, rounded, with their total and the longest.
 * @param {{at:number, ms:number}[]} raw  in page time
 * @param {number} start  page time the measured steps began
 */
export function readStalls(raw, start) {
  const stalls = raw
    .filter((s) => s.at >= start - 20 && s.ms > STALL_MS)
    .map((s) => ({ at: Math.round(s.at - start), ms: Math.round(s.ms) }));
  return {
    stalls,
    total: stalls.reduce((a, s) => a + s.ms, 0),
    longest: stalls.reduce((a, s) => Math.max(a, s.ms), 0),
  };
}

/**
 * Self time in a V8 CPU profile, summed by where it was spent, largest first.
 * `where(node)` names a sample's frame; it defaults to the function and the file
 * it's in. The engine's idle and bookkeeping frames are left out.
 * @param {{nodes:{id:number, callFrame:{functionName:string, url:string, lineNumber:number}}[], samples:number[], timeDeltas:number[]}} profile
 * @param {(node:any) => string} [where]
 */
export function selfTime(profile, where = defaultWhere) {
  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  /** @type {Map<string, number>} */
  const sums = new Map();
  profile.samples.forEach((id, i) => {
    const node = byId.get(id);
    if (!node || ["(idle)", "(program)", "(root)"].includes(node.callFrame.functionName)) return;
    const key = where(node);
    sums.set(key, (sums.get(key) ?? 0) + (profile.timeDeltas[i] ?? 0) / 1000);
  });
  return [...sums].sort((a, b) => b[1] - a[1]).map(([at, ms]) => ({ at, ms: Math.round(ms * 10) / 10 }));
}

/** @param {any} node */
function defaultWhere(node) {
  const f = node.callFrame;
  const file = (f.url || "").split("/").pop()?.replace(/\?.*/, "") ?? "";
  return `${f.functionName || "(anonymous)"}${file ? ` ${file}:${f.lineNumber + 1}` : ""}`;
}

/**
 * Names frames through the source maps a page serves, when it serves them, so
 * a production build reads as its source. Falls back to the minified frame.
 * @param {string} base  the app's origin
 */
async function sourceMapped(profile, base) {
  /** @type {any} */
  let SourceMapConsumer;
  try {
    ({ SourceMapConsumer } = await import("source-map-js"));
  } catch {
    return defaultWhere;
  }
  /** @type {Map<string, any>} */
  const maps = new Map();
  const urls = new Set(profile.nodes.map((/** @type {any} */ n) => n.callFrame.url).filter((u) => u.startsWith(base)));
  for (const url of urls) {
    try {
      const js = await (await fetch(url)).text();
      const name = js.match(/sourceMappingURL=(\S+)\s*$/)?.[1];
      if (!name || name.startsWith("data:")) continue;
      const res = await fetch(new URL(name, url));
      if (res.ok) maps.set(url, new SourceMapConsumer(await res.json()));
    } catch {
      // A chunk without a map is named as it is.
    }
  }
  return (/** @type {any} */ node) => {
    const f = node.callFrame;
    const pos = maps.get(f.url)?.originalPositionFor({ line: f.lineNumber + 1, column: f.columnNumber });
    if (!pos?.source) return defaultWhere(node);
    const source = String(pos.source).replace(/^.*?\/((?:src|app|lib|node_modules)\/)/, "$1");
    return `${f.functionName || pos.name || "(anonymous)"} ${source}:${pos.line}`;
  };
}

/**
 * One run: a fresh page, the setup, then the measured steps.
 * @param {any} browser
 * @param {{base:string, route:string, engine:string, viewport:{width:number,height:number},
 *   storage:Record<string,string>, setup:string[], measure:string[], until?:string,
 *   timeout:number, outDir:string, name:string, top:number}} o
 */
export async function profileRun(browser, o) {
  const context = await browser.newContext({ viewport: o.viewport });
  await context.addInitScript((storage) => {
    for (const [k, v] of Object.entries(storage)) localStorage.setItem(k, v);
  }, o.storage);
  await context.addInitScript(heartbeat);
  const page = await context.newPage();
  try {
    await page.goto(new URL(o.route, o.base).toString(), { waitUntil: "load", timeout: o.timeout });
    await runActions(page, o.setup, { baseUrl: o.base, timeout: o.timeout });

    const cdp = o.engine === "chromium" ? await context.newCDPSession(page) : null;
    if (cdp) {
      await cdp.send("Profiler.enable");
      await cdp.send("Profiler.setSamplingInterval", { interval: 100 });
      await cdp.send("Profiler.start");
    }
    const start = await page.evaluate(() => performance.now());
    await runActions(page, o.measure, { baseUrl: o.base, timeout: o.timeout });
    if (o.until) await runAction(page, o.until, { baseUrl: o.base, timeout: o.timeout });
    const met = (await page.evaluate(() => performance.now())) - start;

    // Usable once a quiet stretch follows; the last stall before it ends the wait.
    let usable = met;
    const limit = Date.now() + QUIET_LIMIT_MS;
    for (;;) {
      await page.waitForTimeout(100);
      const { now, stalls } = await page.evaluate(() => ({ now: performance.now(), stalls: (/** @type {any} */ (window)).__shotStalls }));
      const last = readStalls(stalls, start).stalls.at(-1);
      const end = last ? Math.max(met, last.at + last.ms) : met;
      usable = end;
      if (now - start - end >= QUIET_MS || Date.now() > limit) break;
    }
    const read = readStalls(await page.evaluate(() => (/** @type {any} */ (window)).__shotStalls), start);

    /** @type {{profile?:string, top?:{at:string, ms:number}[]}} */
    const cpu = {};
    if (cdp) {
      const { profile } = await cdp.send("Profiler.stop");
      mkdirSync(o.outDir, { recursive: true });
      cpu.profile = join(o.outDir, `${o.name}.cpuprofile`);
      writeFileSync(cpu.profile, JSON.stringify(profile));
      cpu.top = selfTime(profile, await sourceMapped(profile, o.base)).slice(0, o.top);
    }
    return { untilMs: Math.round(met), usableMs: Math.round(usable), ...read, ...cpu };
  } finally {
    await context.close();
  }
}

/** The middle value, for a summary over runs. */
export const median = (/** @type {number[]} */ xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor((s.length - 1) / 2)] : 0;
};

/**
 * The summary a person or an agent reads without a viewer.
 * @param {{engine:string, runs:any[]}} r
 */
export function formatProfile({ engine, runs }) {
  const lines = [`${engine}, ${runs.length} run${runs.length === 1 ? "" : "s"}`];
  runs.forEach((run, i) => {
    const stalls = run.stalls.map((/** @type {any} */ s) => `${s.ms} at ${s.at}`).join(", ") || "none";
    lines.push(`  run ${i + 1}: usable ${run.usableMs} ms (--until met at ${run.untilMs} ms); stalls over ${STALL_MS} ms: ${stalls}`);
  });
  if (runs.length > 1) {
    lines.push(
      `  median: usable ${median(runs.map((r) => r.usableMs))} ms, blocked ${median(runs.map((r) => r.total))} ms, ` +
        `longest stall ${median(runs.map((r) => r.longest))} ms`,
    );
  }
  const last = runs.at(-1);
  if (last?.top?.length) {
    lines.push(`  self time, last run (ms):`);
    for (const t of last.top) lines.push(`    ${String(t.ms).padStart(7)}  ${t.at}`);
  }
  return lines.join("\n");
}
