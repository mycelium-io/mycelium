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

type Agent = { name: string; status: string; pane: string };

const bar = document.getElementById("terminal-bar")!;
/** How often to ask herdr who's running while the window is in front. */
const AGENTS_EVERY_MS = 5000;

/** One line over herdr: what this window is when nothing runs in it, and who
 *  is waiting for an answer when someone is. Hidden otherwise. */
function showAgents(agents: Agent[]) {
  const waiting = agents.filter((a) => a.status === "blocked");
  bar.replaceChildren();
  bar.removeAttribute("data-tone");
  if (waiting.length) {
    const names = waiting.map((a) => a.name);
    const who = names.length === 1 ? `${names[0]} is` : `${names.slice(0, -1).join(", ")} and ${names.at(-1)} are`;
    const line = document.createElement("span");
    const what = names.length === 1 ? "Open its pane and answer what it's asking." : "Answer each in its pane.";
    line.textContent = `${who} waiting for you. ${what}`;
    const open = document.createElement("button");
    open.textContent = `Show ${names[0]}`;
    open.onclick = () => {
      void invoke("terminal_open", { pane: waiting[0].pane, cols: term.cols, rows: term.rows }).catch(() => {});
      term.focus();
    };
    bar.append(line, open);
    bar.dataset.tone = "waiting";
    bar.hidden = false;
  } else if (!agents.length) {
    const line = document.createElement("span");
    line.textContent =
      "This is where your agents run. Each agent you add opens here; come back when one is waiting for you.";
    bar.append(line);
    bar.hidden = false;
  } else {
    bar.hidden = true;
  }
}

async function checkAgents() {
  if (document.visibilityState !== "visible") return;
  try {
    showAgents(await invoke<Agent[]>("terminal_agents"));
  } catch {
    // An older app without the call, or herdr not answering: say nothing.
  }
}

async function start() {
  await listen<string>("terminal-data", (e) => term.write(e.payload));
  await listen("terminal-exit", () => say("herdr detached. Close this window, or open it again from the tray."));
  term.onData((data) => void invoke("terminal_write", { data }).catch(() => {}));
  term.onResize(({ cols, rows }) => void invoke("terminal_resize", { cols, rows }).catch(() => {}));
  // The terminal, not the page: the bar over it changes its size too.
  new ResizeObserver(() => fit.fit()).observe(document.getElementById("terminal")!);
  void checkAgents();
  setInterval(() => void checkAgents(), AGENTS_EVERY_MS);
  window.addEventListener("focus", () => void checkAgents());
  const pane = new URLSearchParams(location.search).get("pane");
  try {
    await invoke("terminal_open", { pane, cols: term.cols, rows: term.rows });
    term.focus();
  } catch (e) {
    say(String(e));
  }
}

void start();
