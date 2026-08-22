// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The frontend↔backend route contract.
 *
 * Every `/api/...` the UI fetches is served by exactly one of two things: a
 * local Next route handler under `src/app/api/`, or a backend endpoint reached
 * through the catch-all proxy. The proxy is untyped by construction — it
 * forwards whatever path it is handed — so a renamed or deleted backend route
 * fails at runtime with a 404 in a panel, not at build time.
 *
 * This closes that seam against the committed `openapi.json` (the same spec the
 * OpenAPI client is generated from, and the same one CI asserts is current), so
 * a backend route change that strands a fetch fails here instead.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = resolve(HERE, "..");
const FRONTEND_DIR = resolve(SRC_DIR, "..");
const OPENAPI = resolve(FRONTEND_DIR, "..", "openapi.json");

/** A used segment whose value is only known at runtime: `${roomName}`, `[name]`. */
const PARAM = "{}";

/**
 * Backend params declared with FastAPI's `:path` converter, which swallow
 * slashes. A memory key is namespaced by design (`decisions/cutover`), so
 * `/memory/{key}` is one declared segment against two or more used ones.
 */
const SLASHY_PARAMS = new Set(["{key}"]);

/** Mirrors the one alias the proxy applies (src/app/api/[...path]/route.ts). */
const PROXY_ALIASES: Record<string, string> = { "/api/health": "/health" };

/** Recursively list files under `dir`. */
function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : walk(full);
    return [full];
  });
}

/**
 * Replace `${...}` interpolations with the param marker, balancing braces so a
 * nested template (`${a ? `${b}` : c}`) collapses to a single marker.
 */
function collapseInterpolations(path: string): string {
  let out = "";
  for (let i = 0; i < path.length; i++) {
    if (path[i] === "$" && path[i + 1] === "{") {
      let depth = 1;
      i += 2;
      while (i < path.length && depth > 0) {
        if (path[i] === "{") depth++;
        else if (path[i] === "}") depth--;
        i++;
      }
      i--;
      out += PARAM;
    } else {
      out += path[i];
    }
  }
  return out;
}

/** `/api/rooms/${name}/memory?x=1` -> `["api", "rooms", "{}", "memory"]`. */
function usedSegments(path: string): string[] {
  return collapseInterpolations(path).split("?")[0].split("#")[0].split("/").filter(Boolean);
}

/** `/api/rooms/{room_name}/memory` -> `["api", "rooms", "{room_name}", "memory"]`. */
function declaredSegments(path: string): string[] {
  return path
    .split("/")
    .filter(Boolean)
    .map((s) => (s.startsWith("[") ? `{${s}}` : s));
}

const isParam = (segment: string): boolean => /^\{.*\}$/.test(segment);

/**
 * A used path satisfies a declared one when every segment lines up: a concrete
 * value fills a declared param, and an interpolated value fills anything (the
 * UI can't know at build time that `${decision}` is only ever `accept` or
 * `decline`). Literal-against-literal is exact — that's what catches a renamed
 * or dropped route.
 */
function matches(used: string[], declared: string[]): boolean {
  const last = declared.length - 1;
  if (last >= 0 && SLASHY_PARAMS.has(declared[last])) {
    if (used.length < declared.length) return false;
  } else if (used.length !== declared.length) {
    return false;
  }
  return declared.every((d, i) => isParam(d) || used[i] === PARAM || d === used[i]);
}

/** Route handlers this app serves itself, from the `src/app/api` tree. */
function localHandlers(): string[][] {
  const apiDir = join(SRC_DIR, "app", "api");
  return walk(apiDir)
    .filter((f) => /[/\\]route\.tsx?$/.test(f))
    .map((f) => dirname(f).slice(apiDir.length).split(/[/\\]/).filter(Boolean))
    // The catch-all IS the proxy to the backend. Counting it as a local handler
    // would make every path under /api/ valid and this test vacuous.
    .filter((segs) => !segs.some((s) => s.startsWith("[...")))
    .map((segs) => declaredSegments(["api", ...segs].join("/")));
}

/** Paths the backend declares, from the committed spec. */
function backendPaths(): string[][] {
  const spec = JSON.parse(readFileSync(OPENAPI, "utf8")) as { paths: Record<string, unknown> };
  return Object.keys(spec.paths).map(declaredSegments);
}

/** Every `/api/...` string or template literal in the frontend source. */
function usedPaths(): { path: string; file: string }[] {
  const found: { path: string; file: string }[] = [];
  for (const file of walk(SRC_DIR)) {
    if (!/\.tsx?$/.test(file)) continue;
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(/(["'`])(\/api\/[^"'`\n]*)\1/g)) {
      const path = m[2];
      // `/api/*`, `/api/[...path]` and `/api/…` name the proxy itself in prose
      // and route definitions; they are not fetches.
      if (/[*[\s…]|\.\./.test(path)) continue;
      found.push({ path, file: file.slice(FRONTEND_DIR.length + 1) });
    }
  }
  return found;
}

describe("frontend /api routes", () => {
  const local = localHandlers();
  const backend = backendPaths();
  const used = usedPaths();

  it("finds the fetch surface to check", () => {
    // Guards the scanner itself: a refactor that moves every fetch behind a
    // path builder would silently empty this suite rather than fail it.
    expect(used.length).toBeGreaterThan(20);
    expect(local.length).toBeGreaterThan(0);
  });

  it.each(used)("$path ($file) is served by a local handler or the backend spec", ({ path }) => {
    const target = usedSegments(PROXY_ALIASES[path.split("?")[0]] ?? path);
    const served =
      local.some((declared) => matches(target, declared)) ||
      backend.some((declared) => matches(target, declared));
    expect(served, `${path} matches no local route handler and no path in openapi.json`).toBe(true);
  });
});
