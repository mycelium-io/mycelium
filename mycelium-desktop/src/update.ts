// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The update's own window: the mark, the version, and how far along the
// download is, until the app restarts into the new one. `?preview=<phase>`
// draws it with made-up numbers, outside the app.

import "./style.css";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Phase = "downloading" | "installing" | "restarting" | "failed";

interface Progress {
  version: string;
  current: string;
  phase: Phase;
  received: number;
  total: number | null;
  error: string | null;
}

const root = document.getElementById("update")!;
const title = document.getElementById("update-title")!;
const bar = document.getElementById("update-bar")!;
const fill = document.getElementById("update-fill")!;
const line = document.getElementById("update-line")!;
const note = document.getElementById("update-note")!;

function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_048_576)} MB`;
}

function draw(p: Progress) {
  root.dataset.phase = p.phase;
  title.textContent = p.phase === "failed" ? "The update didn't install" : `Updating to Mycelium ${p.version}`;
  const share = p.total ? Math.min(1, p.received / p.total) : null;
  // With no size given, the bar runs back and forth rather than guessing.
  bar.classList.toggle("indeterminate", p.phase === "downloading" && share === null);
  fill.style.width = p.phase === "downloading" ? `${Math.round((share ?? 0) * 100)}%` : "100%";
  if (share !== null) bar.setAttribute("aria-valuenow", String(Math.round(share * 100)));
  if (p.phase === "downloading") {
    line.textContent = p.total
      ? `${megabytes(p.received)} of ${megabytes(p.total)}`
      : p.received
        ? `${megabytes(p.received)} so far`
        : "Starting the download…";
  } else if (p.phase === "installing") {
    line.textContent = "Installing…";
  } else if (p.phase === "restarting") {
    line.textContent = "Restarting…";
  } else {
    line.textContent = p.error ?? "Something went wrong.";
  }
  note.textContent =
    p.phase === "failed"
      ? `You still have ${p.current}. Try again from Check for Updates… in the menu.`
      : "Mycelium restarts itself when it's ready. Your agents keep running in herdr.";
}

const PREVIEW: Record<Phase, Progress> = {
  downloading: { version: "3.0.34", current: "3.0.33", phase: "downloading", received: 96_468_992, total: 251_658_240, error: null },
  installing: { version: "3.0.34", current: "3.0.33", phase: "installing", received: 251_658_240, total: 251_658_240, error: null },
  restarting: { version: "3.0.34", current: "3.0.33", phase: "restarting", received: 251_658_240, total: 251_658_240, error: null },
  failed: { version: "3.0.34", current: "3.0.33", phase: "failed", received: 0, total: null, error: "The download stopped: the network connection was lost." },
};

async function start() {
  const preview = new URLSearchParams(location.search).get("preview") as Phase | null;
  if (preview && preview in PREVIEW) {
    draw(PREVIEW[preview]);
    return;
  }
  await listen<Progress>("update-progress", (e) => draw(e.payload));
  const now = await invoke<Progress | null>("update_progress").catch(() => null);
  if (now) draw(now);
}

void start();
