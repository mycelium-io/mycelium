// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  isJsonRawText,
  parseJsonRawText,
  prettyPrintJsonRawText,
} from "@/lib/json-text";

describe("memory raw JSON helpers", () => {
  it("accepts object and array literals", () => {
    expect(isJsonRawText('{"a":1}')).toBe(true);
    expect(isJsonRawText("[1,2]")).toBe(true);
    expect(parseJsonRawText(' {"x": true} ')).toEqual({ x: true });
  });

  it("rejects markdown and partial JSON", () => {
    expect(isJsonRawText("See [[link]]")).toBe(false);
    expect(isJsonRawText("{not json}")).toBe(false);
    expect(isJsonRawText("")).toBe(false);
  });

  it("pretty-prints without adding API fields", () => {
    expect(prettyPrintJsonRawText('{"b":2,"a":1}')).toBe(
      '{\n  "b": 2,\n  "a": 1\n}',
    );
  });
});
