// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The agents terminal: herdr, drawn with xterm.js. Keystrokes go to herdr and
// its screen comes back; the app starts nothing here but herdr itself.

import "./style.css";
import "@xterm/xterm/css/xterm.css";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

const note = document.getElementById("terminal-note")!;

const term = new Terminal({
  fontFamily: '"Geist Mono", "SF Mono", "JetBrains Mono", Menlo, monospace',
  fontSize: 13,
  cursorBlink: true,
  allowProposedApi: true,
  theme: {
    background: "#0c0e11",
    foreground: "#e8ebee",
    cursor: "#5cc7d2",
    selectionBackground: "rgba(92, 199, 210, 0.3)",
  },
});
const fit = new FitAddon();
term.loadAddon(fit);
term.open(document.getElementById("terminal")!);
fit.fit();

function say(text: string) {
  note.textContent = text;
  note.hidden = false;
}

async function start() {
  await listen<string>("terminal-data", (e) => term.write(e.payload));
  await listen("terminal-exit", () => say("herdr detached. Close this window, or open it again from the tray."));
  term.onData((data) => void invoke("terminal_write", { data }).catch(() => {}));
  term.onResize(({ cols, rows }) => void invoke("terminal_resize", { cols, rows }).catch(() => {}));
  new ResizeObserver(() => fit.fit()).observe(document.body);
  const pane = new URLSearchParams(location.search).get("pane");
  try {
    await invoke("terminal_open", { pane, cols: term.cols, rows: term.rows });
    term.focus();
  } catch (e) {
    say(String(e));
  }
}

void start();
