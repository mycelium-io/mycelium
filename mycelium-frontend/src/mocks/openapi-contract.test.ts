// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mock fixtures must answer in the shapes the backend declares.
 *
 * `src/mocks/` is what the UI is *developed* against: `pnpm dev:mock` and every
 * screenshot run resolve `/api/*` here rather than against a backend. So when a
 * fixture drifts from the real response shape, the app is built against a
 * fiction — and the divergence surfaces in production, where the field the panel
 * reads is simply absent.
 *
 * `api-contract.test.ts` proves the frontend only fetches paths the backend
 * declares. This proves the bodies behind those paths are the ones it declares
 * too. Both read the committed `openapi.json`, which CI separately asserts is
 * current, so neither can pass against a stale spec.
 *
 * The request list is derived from the spec, not hand-written: every GET the
 * mock answers is validated. A route the mock doesn't serve is skipped (the
 * proxy 404s it, which is honest), so this grows coverage on its own as mocks
 * are added.
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
 * Concrete values for the spec's path parameters, chosen from the fixtures so a
 * request resolves to real mock data rather than a 404. `key:path` is FastAPI's
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
  // A path with a parameter we have no fixture value for can't be requested
  // honestly; skip it rather than invent one.
  return /\{[^}]+\}/.test(filled) ? null : filled + (QUERY[path] ?? "");
}

/**
 * Writes the UI makes, with a body each. A POST can't be derived from the spec
 * the way a GET can — it needs something plausible to send — so these are
 * listed, and the response is still checked against whatever the spec declares.
 */
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
    // A route the mock doesn't serve falls through to a 404 in the browser too,
    // which is honest; there is no shape to check.
    const response = await handleMock(request(route));
    if (response && response.status < 300) answered.push(route);
  }
  return answered;
}

const ROUTES = await mockedRoutes();

describe("mock fixtures against the backend spec", () => {
  it("finds the mocked surface to check", () => {
    // Guards the derivation: a change that made every request fall through
    // would leave an empty, green suite rather than a red one.
    expect(ROUTES.length).toBeGreaterThan(12);
  });

  it.each(ROUTES)("$method $path matches its declared response shape", async (route) => {
    const response = (await handleMock(request(route)))!;
    const operation = SPEC.paths[route.path][route.method.toLowerCase()];
    const schema = statusSchema(operation, response.status);
    // A mock that answers 201 where the spec only documents 200 is itself drift,
    // so the status has to resolve to a declared response.
    expect(schema, `${route.method} ${route.url}: no ${response.status} in the spec`).not.toBeNull();
    const errors = validate(await response.json(), schema!, SPEC, {
      rejectUnknownProperties: true,
    });
    expect(errors, `${route.method} ${route.url}\n  ${errors.join("\n  ")}`).toEqual([]);
  });
});
