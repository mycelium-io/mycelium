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
      detail: "not a shell",
      slow: false,
      waiting: null,
      passed: [],
    });
    expect(startReport({ result: { passed: ["Trusted the folder for Claude Code", 3, ""] } }).passed).toEqual([
      "Trusted the folder for Claude Code",
    ]);
    expect(startReport({ result: { step: "shell", slow: true, pane: "w5:p1" } })).toMatchObject({ slow: true });
    // The last step, with its terminal, and a start that stopped at a prompt.
    expect(startReport({ result: { step: "intro", pane: "w5:p1" } })).toMatchObject({ step: "intro", pane: "w5:p1" });
    expect(startReport({ result: { pane: "w5:p1", waiting: "Codex is asking you to sign in" } })).toMatchObject({
      waiting: "Codex is asking you to sign in",
    });
    expect(startReport({ result: { slow: "yes" } })).toMatchObject({ slow: false });
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
    // One that exited says so, and points at what it printed, not at a prompt to answer.
    const exited = startHelp("exited", names);
    expect(exited.happened).toBe("Codex exited before it started on studio-mini.");
    expect(exited.steps.join(" ")).toContain("showing what Codex printed");
    expect(startReport({ result: { why: "exited" } }).why).toBe("exited");
    // One its shell couldn't find says it isn't installed, and to install it there.
    const missing = startHelp("missing", names);
    expect(missing.happened).toBe("Codex isn't installed on studio-mini.");
    expect(missing.steps.join(" ")).toContain("Install Codex on studio-mini");
    expect(startReport({ result: { why: "missing" } }).why).toBe("missing");
    // One that needs setting up first (a sign-in) says what the runner found, as its step.
    const signIn = "Codex isn't signed in here yet. Run `codex` once in a terminal. Then try again.";
    const setup = startHelp("setup", { ...names, detail: signIn });
    expect(setup.happened).toBe("Codex needs setting up on studio-mini before an agent can start in it.");
    expect(setup.steps).toEqual([signIn]);
    expect(startReport({ result: { why: "setup" } }).why).toBe("setup");
    // A host that said why leads with it, and doesn't blame the agent CLI.
    const refused = startHelp("host", { ...names, detail: "agent name reviewer is already used" });
    expect(refused.happened).toBe("studio-mini couldn't start Codex: agent name reviewer is already used");
    expect(refused.steps.join(" ")).not.toContain("run it yourself");
    // A machine not signed in to a hub with sign-in on is told to sign in there,
    // in the runner's words when it gave them.
    const signedOut = startHelp("signin", names);
    expect(signedOut.happened).toBe(
      "studio-mini isn't signed in to this hub, so @reviewer couldn't get its own credential here.",
    );
    expect(signedOut.steps[0]).toBe("In a terminal on studio-mini, run mycelium login and finish signing in.");
    expect(signedOut.short).toBe("studio-mini isn't signed in to this hub");
    expect(startHelp("signin", { ...names, detail: "Sign in here as its owner." }).happened).toBe(
      "Sign in here as its owner.",
    );
    expect(startReport({ result: { why: "signin" } }).why).toBe("signin");
    // Plain words for people: no em dashes anywhere in it.
    for (const help of [shell, cli, exited, missing, setup, signedOut, startHelp(null, names)]) {
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
  it("orders frameworks startable and found, startable, found, then neither", () => {
    const sorted = sortFrameworks([
      framework({ id: "zed", name: "Zed", installed: false, launchable: false }),
      framework({ id: "amp", name: "Amp", launchable: false, note: "herdr can't start it" }),
      framework({ id: "codex", name: "Codex", installed: false }),
      framework({ id: "opencode", name: "opencode" }),
      framework({ id: "claude", name: "Claude Code" }),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["claude", "opencode", "codex", "amp", "zed"]);
  });

  it("offers a CLI the scan didn't find when the host can start it, after the found ones", () => {
    const mac = runner({
      frameworks: [
        framework({ id: "codex", name: "Codex", installed: false }),
        framework({ id: "claude", name: "Claude Code" }),
        framework({ id: "amp", name: "Amp", launchable: false }),
      ],
    });
    expect(launchable(mac).map((f) => f.id)).toEqual(["claude", "codex"]);
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
