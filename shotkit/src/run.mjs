// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Run a command the way a terminal would, and keep the escape codes.
 *
 * A screenshot of `mycelium memory ls` is worth taking only if it looks like
 * the real thing, and Rich decides that from the process it finds itself in: no
 * tty means no color, no box-drawing, no columns. So the command is run under
 * `script(1)`, which allocates a real pty on both supported hosts — that is the
 * whole reason this module exists rather than a bare `spawn`.
 *
 * `COLUMNS` is set as well as the pty being allocated. `script` gives the child
 * the size of *our* terminal, which under an agent is either absent or wrong,
 * and Rich reads `COLUMNS` ahead of the ioctl — so the env var is what actually
 * decides the width of the output in the image.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { platform } from "node:os";

const SCRIPT_BIN = ["/usr/bin/script", "/bin/script"].find((p) => existsSync(p));

/** Shell-quote one argv entry for the single command string `script` takes. */
export function shellQuote(arg) {
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(arg)) return arg;
  return `'${arg.replace(/'/g, `'\\''`)}'`;
}

/**
 * @typedef {object} RunOptions
 * @property {string[]} argv command and arguments; joined into one shell line
 * @property {string} [cwd]
 * @property {number} [cols] width handed to the child (default 100)
 * @property {number} [rows]
 * @property {number} [timeout] ms before SIGKILL (default 60000)
 * @property {Record<string,string>} [env] extra environment
 * @property {boolean} [pty] allocate a pty (default true when `script` exists)
 */

/**
 * @param {RunOptions} opts
 * @returns {Promise<{output:string, exitCode:number, ms:number, command:string, pty:boolean, timedOut:boolean}>}
 */
export function runCommand(opts) {
  const cols = opts.cols ?? 100;
  const rows = opts.rows ?? 50;
  const line = opts.argv.map(shellQuote).join(" ");
  const usePty = (opts.pty ?? true) && Boolean(SCRIPT_BIN);

  const env = {
    ...process.env,
    TERM: "xterm-256color",
    COLUMNS: String(cols),
    LINES: String(rows),
    FORCE_COLOR: "1",
    CLICOLOR_FORCE: "1",
    PYTHONIOENCODING: "utf-8",
    PYTHONUNBUFFERED: "1",
    ...opts.env,
  };
  delete env.NO_COLOR;

  let file;
  let args;
  if (usePty && platform() === "darwin") {
    // BSD script: the typescript path comes first, then the command argv.
    file = SCRIPT_BIN;
    args = ["-q", "/dev/null", "/bin/sh", "-c", line];
  } else if (usePty) {
    // util-linux script: -e propagates the child's exit status, -c takes the
    // command, and the typescript is discarded.
    file = SCRIPT_BIN;
    args = ["-qec", line, "/dev/null"];
  } else {
    file = "/bin/sh";
    args = ["-c", line];
  }

  const started = Date.now();
  return new Promise((resolve) => {
    const child = spawn(file, args, { cwd: opts.cwd ?? process.cwd(), env, stdio: ["ignore", "pipe", "pipe"] });
    /** @type {Buffer[]} */
    const chunks = [];
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, opts.timeout ?? 60_000);

    child.stdout.on("data", (d) => chunks.push(d));
    child.stderr.on("data", (d) => chunks.push(d));
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({
        output: `\x1b[31m${err.message}\x1b[0m`,
        exitCode: 127,
        ms: Date.now() - started,
        command: line,
        pty: usePty,
        timedOut,
      });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        output: Buffer.concat(chunks).toString("utf8"),
        exitCode: code ?? 0,
        ms: Date.now() - started,
        command: line,
        pty: usePty,
        timedOut,
      });
    });
  });
}

export const ptyAvailable = Boolean(SCRIPT_BIN);
