import { describe, expect, it } from "vitest";
import {
  describeJob,
  hostMissing,
  hostOf,
  isMine,
  launchable,
  sortFrameworks,
  startHelp,
  startReport,
  startsInHerdr,
} from "./runners";
import { framework, runner } from "./runners.fixture";
import type { RunnerJob } from "./api";

describe("a start that stopped", () => {
  it("reads how far it got off the job, and nothing it doesn't know", () => {
    expect(startReport({ result: { step: "shell", why: "shell", pane: "w5:p1", detail: "not a shell" } })).toEqual({
      step: "shell",
      why: "shell",
      pane: "w5:p1",
      screen: null,
      detail: "not a shell",
    });
    expect(startReport({ result: { step: "warp", why: 3 } })).toMatchObject({ step: null, why: null });
    expect(startReport(null)).toMatchObject({ step: null, why: null, pane: null });
  });

  it("says what happened and what to do, in order, for each reason", () => {
    const names = { machine: "studio-mini", cli: "Codex", handle: "reviewer" };
    const shell = startHelp("shell", names);
    expect(shell.happened).toContain("didn't get to its shell prompt in time");
    expect(shell.steps.at(-1)).toContain("reuses the same terminal");
    const cli = startHelp("cli", names);
    expect(cli.happened).toContain("Codex opened on studio-mini but didn't finish starting");
    expect(cli.short).toBe("Codex is waiting for something in its terminal on studio-mini");
    expect(startHelp("host", names).steps.join(" ")).toContain("runner.log");
    // Plain words for people: no em dashes anywhere in it.
    for (const help of [shell, cli, startHelp(null, names)]) {
      expect([help.happened, help.short, ...help.steps].join(" ")).not.toContain("—");
    }
  });
});

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

  it("starts nothing on a machine whose host isn't running", () => {
    expect(launchable(runner()).map((f) => f.id)).toEqual(["claude", "opencode"]);
    expect(launchable(runner({ herdr: false }))).toEqual([]);
    expect(hostMissing(runner())).toBe(
      "herdr isn't running on julias-mbp. Install it from https://herdr.dev and start it, then this machine can start agents.",
    );
  });

  it("names a runner's own host, and herdr when it doesn't say", () => {
    expect(hostOf(runner()).name).toBe("herdr");
    expect(startsInHerdr(runner())).toBe(true);
    const omni = runner({ host: "omnigent" });
    expect(hostOf(omni).name).toBe("Omnigent");
    expect(startsInHerdr(omni)).toBe(false);
    expect(hostMissing(omni)).toBe(
      "Omnigent isn't running on julias-mbp. Start it there with `omnigent start`, then this machine can start agents.",
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
