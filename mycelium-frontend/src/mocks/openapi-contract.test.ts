// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mock fixtures must answer in the shapes the backend declares.
 *
 * `src/mocks/` is what the UI is *developed* against — `pnpm dev:mock` and every
 * screenshot run resolve `/api/*` here — so a drifted fixture means the app is
 * built against a fiction, and the field the panel reads is absent in
 * production.
 *
 * Where `api-contract.test.ts` proves the frontend only fetches paths the
 * backend declares, this proves the bodies behind them match too. Both read the
 * committed `openapi.json`, which CI separately asserts is current.
 *
 * The request list is derived from the spec: every GET the mock answers is
 * validated, and a route the mock doesn't serve is skipped, so coverage grows
 * as mocks are added.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ROOM_FIXTURES } from "./fixtures";
import { handleMock } from "./handlers";
import { statusSchema, successSchema, validate, type Spec } from "@/lib/openapi-schema";

const HERE = dirname(fileURLToPath(import.meta.url));
const SPEC: Spec = JSON.parse(
  readFileSync(resolve(HERE, "..", "..", "..", "openapi.json"), "utf8"),
);

const ROOM = "atlas-migration";
const FIXTURE = ROOM_FIXTURES[ROOM];

/**
 * Values for the spec's path parameters, taken from the fixtures so a request
 * resolves to real mock data rather than a 404. `key:path` is FastAPI's
 * slash-swallowing converter, which is how a namespaced memory key travels.
 */
const PATH_PARAMS: Record<string, string> = {
  "{room_name}": ROOM,
  "{key:path}": FIXTURE.memories[0].key,
  "{key}": FIXTURE.memories[0].key,
  "{short_id}": FIXTURE.episodes[0].short_id,
};

/** Query strings for the routes whose mock returns 404 without one. */
const QUERY: Record<string, string> = {
  "/api/rooms/{room_name}/links": `?key=${encodeURIComponent(FIXTURE.memories[0].key)}`,
  "/api/rooms/{room_name}/links/expand": `?key=${encodeURIComponent(FIXTURE.memories[0].key)}`,
  "/api/search": "?q=cutover",
};

function fill(path: string): string | null {
  let filled = path;
  for (const [param, value] of Object.entries(PATH_PARAMS)) {
    filled = filled.split(param).join(encodeURI(value));
  }
  // A parameter with no fixture value can't be filled honestly; skip it.
  return /\{[^}]+\}/.test(filled) ? null : filled + (QUERY[path] ?? "");
}

/** Writes the UI makes. A POST needs a body, so unlike the GETs these are
 *  listed by hand; the response is still checked against the spec. */
const WRITES: { path: string; body: unknown }[] = [
  {
    path: "/api/rooms/{room_name}/memory",
    body: { items: [{ key: "context/from-a-test", value: "written by the contract test" }] },
  },
  { path: "/api/rooms/{room_name}/memory/search", body: { query: "cutover" } },
  { path: "/api/rooms/{room_name}/plan/tasks", body: { slug: "tasks", text: "a new task" } },
  { path: "/api/rooms", body: { name: "a-new-room" } },
];

interface Route {
  path: string;
  url: string;
  method: "GET" | "POST";
  body?: unknown;
}

function request({ url, method, body }: Route): Request {
  return new Request(`http://mock${url}`, {
    method,
    ...(body === undefined
      ? {}
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
}

/** Every operation the spec declares that the mock router actually answers. */
async function mockedRoutes(): Promise<Route[]> {
  const candidates: Route[] = [];
  for (const [path, operations] of Object.entries(SPEC.paths)) {
    const url = "get" in operations ? fill(path) : null;
    if (url && successSchema(operations.get)) candidates.push({ path, url, method: "GET" });
  }
  for (const { path, body } of WRITES) {
    const url = fill(path);
    if (url) candidates.push({ path, url, method: "POST", body });
  }

  const answered: Route[] = [];
  for (const route of candidates) {
    // A route the mock doesn't serve 404s in the browser too — no shape to check.
    const response = await handleMock(request(route));
    if (response && response.status < 300) answered.push(route);
  }
  return answered;
}

const ROUTES = await mockedRoutes();

describe("mock fixtures against the backend spec", () => {
  it("finds the mocked surface to check", () => {
    // Guards the derivation: a change that made every request fall through would
    // leave an empty, green suite.
    expect(ROUTES.length).toBeGreaterThan(12);
  });

  it.each(ROUTES)("$method $path matches its declared response shape", async (route) => {
    const response = (await handleMock(request(route)))!;
    const operation = SPEC.paths[route.path][route.method.toLowerCase()];
    const schema = statusSchema(operation, response.status);
    // A status the spec doesn't document is itself drift.
    expect(schema, `${route.method} ${route.url}: no ${response.status} in the spec`).not.toBeNull();
    const errors = validate(await response.json(), schema!, SPEC, {
      rejectUnknownProperties: true,
    });
    expect(errors, `${route.method} ${route.url}\n  ${errors.join("\n  ")}`).toEqual([]);
  });
});
