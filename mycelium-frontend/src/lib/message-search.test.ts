// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ALIASES,
  CLOSED_VALUES,
  FIELDS,
  SORTS,
  TIME_KEYS,
  freeText,
  hasClause,
  hasScope,
  hintAt,
  toggleClause,
  withSort,
} from "@/lib/message-search";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = JSON.parse(
  readFileSync(resolve(HERE, "..", "..", "..", "contracts", "message-search.json"), "utf8"),
);

describe("the search grammar, as the find bar knows it", () => {
  it("matches the frozen contract the hub and the CLI assert against", () => {
    expect(FIELDS.map((f) => f.name)).toEqual(CONTRACT.fields);
    expect(ALIASES).toEqual(CONTRACT.aliases);
    expect(TIME_KEYS).toEqual(CONTRACT.time_keys);
    expect(SORTS).toEqual(CONTRACT.sorts);
    expect(CLOSED_VALUES).toEqual(CONTRACT.closed_values);
  });

  it("says a closed field's values the way the contract has them", () => {
    for (const f of FIELDS) {
      if (f.name in CLOSED_VALUES) expect(f.value).toBe(CLOSED_VALUES[f.name].join("|"));
    }
  });
});

describe("freeText", () => {
  it("keeps the words and phrases, and drops scope and exclusions", () => {
    expect(freeText('from:avery @builder apple "pay sheet" -stripe after:2d sort:oldest')).toEqual([
      "apple",
      "pay sheet",
    ]);
  });

  it("keeps a word with a colon that names no field", () => {
    expect(freeText("https://stripe.test note:this")).toEqual(["https://stripe.test", "note:this"]);
  });
});

describe("toggleClause", () => {
  it("adds a clause, and takes the same one out again", () => {
    const on = toggleClause("apple", "from", "avery");
    expect(on).toBe("apple from:avery");
    expect(hasClause(on, "from", "avery")).toBe(true);
    expect(toggleClause(on, "from", "avery")).toBe("apple");
  });

  it("quotes a value with a space in it", () => {
    expect(toggleClause("", "task", "Add Apple Pay")).toBe('task:"Add Apple Pay"');
  });

  it("sets the order once, dropping newest as the default", () => {
    expect(withSort("apple sort:oldest", "relevance")).toBe("apple sort:relevance");
    expect(withSort("apple sort:oldest", "newest")).toBe("apple");
  });
});

describe("hintAt", () => {
  const seen = { task: [{ value: "work/apple-pay", label: "Add Apple Pay", count: 4 }] };

  it("offers fields for the start of a name, open so typing goes on", () => {
    const hint = hintAt("ta", 2, seen)!;
    expect(hint.candidates.map((c) => c.insert)).toEqual(["task:"]);
    expect(hint.candidates[0].open).toBe(true);
  });

  it("offers the values the room carries, by the label a person reads", () => {
    const hint = hintAt("task:apple", 10, seen)!;
    expect(hint.candidates[0]).toMatchObject({ insert: "task:work/apple-pay", primary: "Add Apple Pay" });
    expect(hint.signature?.about).toMatch(/task's thread/);
  });

  it("keeps an alias and a minus as typed", () => {
    expect(hintAt("-stance:a", 9, {})!.candidates.map((c) => c.insert)).toEqual(["-stance:accept"]);
    expect(hintAt("since:to", 8, {})!.candidates.map((c) => c.insert)).toEqual(["since:today"]);
  });

  it("is quiet for a plain word and for a field it does not have", () => {
    expect(hintAt("apple", 5, seen)).toBeNull();
    expect(hintAt("frm:x", 5, seen)).toBeNull();
  });
});

describe("hasScope", () => {
  it("is true for a field with a value, an @handle or a time, and false for words", () => {
    expect(hasScope("apple from:builder")).toBe(true);
    expect(hasScope("@builder")).toBe(true);
    expect(hasScope("after:2h")).toBe(true);
    expect(hasScope("apple from:")).toBe(false);
    expect(hasScope("apple https://x.test")).toBe(false);
  });
});
