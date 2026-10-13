// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { handleMock } from "@/mocks/handlers";
import { claimNeedles } from "./verifier";

describe("claimNeedles", () => {
  it("keeps a quote that sits in plain prose as it is", () => {
    expect(claimNeedles("#502 is approved and green, so ship it", ["#502 is approved and green"])).toContain(
      "#502 is approved and green",
    );
  });

  it("splits a quote around the message's inline code, which is drawn on its own", () => {
    const content = "Also: #1278 (any agent can `@!` another) is approved and green, waiting on you.";
    const needles = claimNeedles(content, ["#1278 (any agent can @! another) is approved and green"]);
    expect(needles).toContain("#1278 (any agent can");
    expect(needles).toContain("another) is approved and green");
    expect(needles.some((n) => n.includes("@!"))).toBe(false);
  });

  it("adds the curled form, since prose is matched after typesetting", () => {
    const needles = claimNeedles("it's approved", ["it's approved"]);
    expect(needles).toContain("it's approved");
    expect(needles).toContain("it’s approved");
  });

  it("drops a piece too short to mean anything", () => {
    expect(claimNeedles("a `b` c", ["a b c"])).toEqual([]);
  });
});

describe("mock verifier", () => {
  const call = async (path: string, method = "GET", body?: unknown) => {
    const res = await handleMock(
      new Request(`http://localhost/api${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
    if (!res) throw new Error(`no mock for ${method} ${path}`);
    return { status: res.status, body: await res.json() };
  };

  it("serves checkout's flag, and It's fine takes it away", async () => {
    const before = (await call("/rooms/checkout/verifier/flags")).body;
    expect(before.find((f: { flag_id: string }) => f.flag_id === "vf1")).toMatchObject({ message_id: "h4", state: "shown" });
    const fine = await call("/rooms/checkout/verifier/flags/vf1/fine", "POST", { by: "julia" });
    expect(fine.body).toMatchObject({ state: "fine", fine_by: "julia" });
    expect((await call("/rooms/checkout/verifier/flags/nope/fine", "POST", {})).status).toBe(404);
  });

  it("runs Learn to done across reads, and refuses a second run while one goes", async () => {
    expect((await call("/verifier/learn", "POST")).status).toBe(202);
    expect((await call("/verifier/learn", "POST")).status).toBe(409);
    let settings = (await call("/verifier/settings")).body;
    for (let i = 0; i < 10 && settings.learning.state === "running"; i++) settings = (await call("/verifier/settings")).body;
    expect(settings).toMatchObject({ using: "learned", learned: 2431, learning: { state: "done" } });
  });
});
