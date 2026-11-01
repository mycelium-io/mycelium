// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The tour points at `data-tour` targets by name. A target renamed or removed
// leaves a stop pointing at nothing, which is how the old tour went stale, so
// every stop's target has to be one the app's source still draws.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { TOUR_STOPS } from "./tour";

const SRC = join(__dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "mocks" ? [] : sources(path);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [path] : [];
  });
}

const drawn = sources(SRC).map((path) => readFileSync(path, "utf8")).join("\n");

/** Whether the source draws `data-tour="<name>"`, written out or as `${id}`. */
function isDrawn(name: string): boolean {
  if (drawn.includes(`data-tour="${name}"`)) return true;
  const [prefix] = name.split("-");
  return drawn.includes(`data-tour={\`${prefix}-\${`) || drawn.includes(`\`${prefix}-\${`);
}

describe("the tour", () => {
  it.each(TOUR_STOPS.map((s) => [s.title, s.element] as const))("%s points at something the app draws", (_title, element) => {
    const name = /data-tour="([^"]+)"/.exec(element)?.[1];
    expect(name).toBeTruthy();
    expect(isDrawn(name as string)).toBe(true);
  });

  it("never mentions the sample room that only the mocks have", () => {
    expect(JSON.stringify(TOUR_STOPS)).not.toMatch(/sample|seeded/i);
  });
});
