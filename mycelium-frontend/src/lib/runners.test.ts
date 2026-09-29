import { describe, expect, it } from "vitest";
import { describeJob, herdrMissing, isMine, launchable, sortFrameworks } from "./runners";
import { framework, runner } from "./runners.fixture";
import type { RunnerJob } from "./api";

describe("which machines are yours", () => {
  it("lists a machine added to this browser, or owned by who you say you are", () => {
    const mac = runner({ id: "julias-mbp", owner: "julia" });
    expect(isMine(mac, ["julias-mbp"], "")).toBe(true);
    expect(isMine(mac, [], "julia")).toBe(true);
    expect(isMine(mac, [], "bob")).toBe(false);
    // Nobody signed in and nothing added: nothing listed, not everything.
    expect(isMine(mac, [], "")).toBe(false);
    expect(isMine(runner({ id: "x", owner: null }), [], "")).toBe(false);
  });
});

describe("runner helpers", () => {
  it("orders frameworks startable, then found but not startable, then missing", () => {
    const sorted = sortFrameworks([
      framework({ id: "zed", name: "Zed", installed: false, launchable: false }),
      framework({ id: "amp", name: "Amp", launchable: false, note: "herdr can't start it" }),
      framework({ id: "opencode", name: "opencode" }),
      framework({ id: "claude", name: "Claude Code" }),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["claude", "opencode", "amp", "zed"]);
  });

  it("starts nothing on a machine without herdr", () => {
    expect(launchable(runner()).map((f) => f.id)).toEqual(["claude", "opencode"]);
    expect(launchable(runner({ herdr: false }))).toEqual([]);
    expect(herdrMissing(runner())).toBe(
      "herdr isn't running on julias-mbp. Install it from https://herdr.dev and start it, then this machine can start agents.",
    );
  });

  it("says a job in a few words", () => {
    const base: Omit<RunnerJob, "kind" | "spec"> = {
      id: "j",
      runner: "r",
      status: "queued",
      result: null,
      error: null,
      created_by: null,
      created_at: "",
      updated_at: "",
    };
    expect(describeJob({ ...base, kind: "launch", spec: { handle: "scout" } })).toBe("Start @scout");
    expect(describeJob({ ...base, kind: "stop", spec: { handle: "scout" } })).toBe("Stop @scout");
    expect(describeJob({ ...base, kind: "scan", spec: {} })).toBe("Scan for agent CLIs");
    expect(describeJob({ ...base, kind: "swarm", spec: { room: "atlas" } })).toBe("Start a swarm in atlas");
  });
});
