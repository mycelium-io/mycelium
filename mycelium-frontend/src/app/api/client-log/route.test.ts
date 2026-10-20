// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/client-log/route";
import { LINES_PER_MINUTE, LINES_PER_SECOND, admit, plainLine, resetClientLog } from "@/lib/client-log";

function post(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://127.0.0.1:3717/api/client-log", {
    method: "POST",
    headers: { "content-type": "application/json", host: "127.0.0.1:3717", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

/** One character, by code point. */
const ch = (code: number) => String.fromCodePoint(code);

describe("POST /api/client-log", () => {
  beforeEach(() => resetClientLog());
  afterEach(() => vi.restoreAllMocks());

  it("writes the page's line to this server's output as one line", async () => {
    const written = vi.spyOn(console, "error").mockImplementation(() => {});
    const res = await POST(post({ line: "stream handler failed\n  at handler (x.ts:1)" }));

    expect(res.status).toBe(204);
    expect(written).toHaveBeenCalledExactlyOnceWith("[page] stream handler failed |   at handler (x.ts:1)");
  });

  // A page on another site can send text/plain without a preflight; JSON it can't.
  it("takes only a JSON body, from this server's own pages", async () => {
    const written = vi.spyOn(console, "error").mockImplementation(() => {});
    expect((await POST(post({ line: "x" }, { "content-type": "text/plain" }))).status).toBe(415);
    expect((await POST(post({ line: "x" }, { origin: "https://elsewhere.example" }))).status).toBe(403);
    expect((await POST(post({ line: "x" }, { origin: "http://127.0.0.1:3717" }))).status).toBe(204);
    expect(written).toHaveBeenCalledOnce();
  });

  it("refuses an empty line", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect((await POST(post({ line: "  " }))).status).toBe(400);
    expect((await POST(post({}))).status).toBe(400);
    expect((await POST(post("not json"))).status).toBe(400);
  });

  it("answers a flood with 429 once the limit is reached", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const codes = [];
    for (let i = 0; i < LINES_PER_SECOND + 2; i++) codes.push((await POST(post({ line: `n${i}` }))).status);
    expect(codes.filter((c) => c === 204)).toHaveLength(LINES_PER_SECOND);
    expect(codes.filter((c) => c === 429)).toHaveLength(2);
  });
});

describe("what reaches the log", () => {
  beforeEach(() => resetClientLog());

  it("is one line with no control character, line break or direction mark", () => {
    const esc = ch(0x1b);
    const forged = `ok\r[page] all clear${ch(0x2028)}${esc}[31mred${esc}[0m${ch(0x202e)}evil${ch(0x7)}${ch(0x85)}`;
    const line = plainLine(forged);
    expect(line).toBe("ok | [page] all clear | [31mred[0mevil");
    for (const code of [0x0, 0x7, 0xd, 0x1b, 0x85, 0x2028, 0x2029, 0x200e, 0x202e, 0x2066]) {
      expect(plainLine(`a${ch(code)}b`)).not.toContain(ch(code));
    }
    expect(plainLine("x".repeat(10_000))).toHaveLength(4_000);
  });

  it("is limited a second and a minute, and counts what was dropped", () => {
    const t0 = 1_000_000;
    for (let i = 0; i < LINES_PER_SECOND; i++) expect(admit("a", t0)).not.toBeNull();
    expect(admit("a", t0)).toBeNull();
    expect(admit("a", t0)).toBeNull();
    expect(admit("next", t0 + 1_000)).toBe("[page] next (2 earlier lines dropped)");

    let ok = LINES_PER_SECOND + 1;
    for (let s = 2; ok < LINES_PER_MINUTE; s++) {
      for (let i = 0; i < LINES_PER_SECOND && ok < LINES_PER_MINUTE; i++, ok++) admit("b", t0 + s * 1_000);
    }
    expect(admit("over the minute", t0 + 59_000)).toBeNull();
    expect(admit("a minute later", t0 + 61_000)).toBe("[page] a minute later (1 earlier line dropped)");
  });
});
