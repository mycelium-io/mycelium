// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Flows: a project's own know-how about getting its UI into a state, committed.
 *
 * Every agent that shoots a project otherwise rediscovers the same moves — how
 * to get past a first-run dialog, how to open a given panel, which route shows
 * which state — and pays for them again, often getting them wrong. A flow is
 * that knowledge written down once, in the source repo where it is reviewed and
 * kept in step with the UI (`shotkit/flows/*.json`, or wherever
 * `shotkit.config.json` says with `flows`):
 *
 *   {
 *     "description": "A task open in the Memory panel drawer",
 *     "uses": ["signed-in"],
 *     "route": "/room/checkout",
 *     "do": ["click:Memory", "click:add-apple-pay", "wait-text:Reply in this thread"]
 *   }
 *
 * A flow is a saved `--do` line plus what a shot starts from: storage, route,
 * viewport, theme. `uses` composes flows, so a setup lives in one place, and
 * the config's `setup` names one that every app capture runs first. The name
 * is the file's basename; a `name` field, if present, must agree with it.
 */

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join, relative } from "node:path";
import { UsageError } from "./args.mjs";
import { FLOWS_DIR, PROJECT_ROOT } from "./project.mjs";

const FIELDS = new Set(["name", "description", "uses", "route", "storage", "do", "viewport", "theme"]);

/** @typedef {{name:string, description?:string, uses?:string[], route?:string, storage?:Record<string,string>, do?:string[], viewport?:string, theme?:string, file:string}} Flow */

/** Every flow the project ships, by name. @returns {Map<string, Flow>} */
export function loadFlows(dir = FLOWS_DIR) {
  const flows = new Map();
  if (!existsSync(dir)) return flows;
  for (const entry of readdirSync(dir).sort()) {
    if (!entry.endsWith(".json")) continue;
    const file = join(dir, entry);
    const where = relative(PROJECT_ROOT, file);
    let flow;
    try {
      flow = JSON.parse(readFileSync(file, "utf8"));
    } catch (e) {
      throw new Error(`flow ${where} is not valid JSON: ${e.message}`);
    }
    const name = basename(entry, ".json");
    if (flow.name !== undefined && flow.name !== name) {
      throw new Error(`flow ${where} says its name is "${flow.name}"; a flow is named by its file`);
    }
    const unknown = Object.keys(flow).filter((k) => !FIELDS.has(k));
    if (unknown.length) {
      throw new Error(`flow ${where}: unknown field ${unknown.join(", ")} (a flow takes ${[...FIELDS].join(", ")})`);
    }
    for (const list of ["uses", "do"]) {
      if (flow[list] !== undefined && !Array.isArray(flow[list])) throw new Error(`flow ${where}: "${list}" is a list`);
    }
    flows.set(name, { ...flow, name, file });
  }
  return flows;
}

/**
 * Several flows, `uses` first, into one starting point. Storage merges with the
 * later flow winning; steps run in order; a route, viewport or theme is the
 * last one any of them names. `segments` says which flow each step came from,
 * so a failing step can be blamed on the flow that holds it.
 *
 * @param {string[]} names
 * @param {Map<string, Flow>} flows
 */
export function resolveFlows(names, flows) {
  /** @type {{storage: Record<string,string>, do: string[], route?: string, viewport?: string, theme?: string, segments: {flow: string, steps: number}[]}} */
  const out = { storage: {}, do: [], segments: [] };
  const done = new Set();
  const visit = (name, path) => {
    if (path.includes(name)) throw new Error(`flows use each other in a loop: ${[...path, name].join(" → ")}`);
    if (done.has(name)) return;
    const flow = flows.get(name);
    if (!flow) {
      const known = [...flows.keys()];
      const where = relative(PROJECT_ROOT, FLOWS_DIR) || ".";
      throw new UsageError(
        `no flow "${name}"${path.length ? ` (used by ${path.at(-1)})` : ""} in ${where}/` +
          (known.length ? `; there is ${known.join(", ")}` : "; it has none"),
      );
    }
    for (const dep of flow.uses ?? []) visit(dep, [...path, name]);
    done.add(name);
    Object.assign(out.storage, flow.storage);
    if (flow.do?.length) {
      out.do.push(...flow.do);
      out.segments.push({ flow: name, steps: flow.do.length });
    }
    for (const k of ["route", "viewport", "theme"]) if (flow[k] !== undefined) out[k] = flow[k];
  };
  for (const name of names) visit(name, []);
  return out;
}

/**
 * Where step `n` (1-based) of a combined list came from: a flow and its own
 * step number, or `flow: null` and the number within the caller's `--do`.
 */
export function flowOfStep(n, segments) {
  let start = 0;
  for (const { flow, steps } of segments) {
    if (n <= start + steps) return { flow, step: n - start };
    start += steps;
  }
  return { flow: null, step: n - start };
}
