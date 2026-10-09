// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { parsePanelId } from "@/lib/room-dock";
import { handleMock } from "@/mocks/handlers";
import { until, when } from "./room-schedules";

const NOW = Date.parse("2026-10-08T12:00:00Z");

describe("schedule helpers", () => {
  it("says when a schedule fires", () => {
    expect(when({ every: "30m", cron: null })).toBe("Every 30m");
    expect(when({ every: null, cron: "0 9 * * 1-5" })).toBe("Cron 0 9 * * 1-5");
  });

  it("counts down to the next run, and says due once it has passed", () => {
    expect(until("2026-10-08T12:12:00Z", NOW)).toBe("in 12m");
    expect(until("2026-10-08T15:00:00Z", NOW)).toBe("in 3h");
    expect(until("2026-10-12T12:00:00Z", NOW)).toBe("in 4d");
    expect(until("2026-10-08T11:00:00Z", NOW)).toBe("due");
    expect(until(null, NOW)).toBe("–");
  });

  it("is a view the dock can name", () => {
    expect(parsePanelId("schedules")).toEqual({ kind: "schedules" });
  });
});

describe("mock schedules", () => {
  const base = "http://localhost/api/rooms/checkout/schedules";
  const call = async (path: string, method = "GET", body?: unknown) => {
    const res = await handleMock(
      new Request(base + path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
    if (!res) throw new Error(`no mock for ${method} ${path}`);
    return { status: res.status, body: res.status === 204 ? null : await res.json() };
  };

  it("lists the room's schedules with the checks the hub runs", async () => {
    const { status, body } = await call("");
    expect(status).toBe(200);
    expect(body.schedules.map((s: { name: string }) => s.name)).toContain("lease-check");
    expect(Object.keys(body.checks)).toContain("stale");
  });

  it("pauses, runs and deletes one", async () => {
    await call("", "POST", { name: "mock-test", owner: "@builder", every: "1h", prompt: "look" });
    expect((await call("/mock-test", "PATCH", { paused: true })).body.state).toBe("paused");
    expect((await call("/mock-test/run", "POST", { wake: true })).body.result).toBe("woke");
    expect((await call("/mock-test")).body.wakes).toBe(1);
    expect((await call("/mock-test", "DELETE")).status).toBe(204);
    expect((await call("/mock-test")).status).toBe(404);
  });
});
