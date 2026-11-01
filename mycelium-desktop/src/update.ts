// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The update's own window: the mark, the version, and how far along the
// download is, until the app restarts into the new one. `?preview=<phase>`
// draws it with made-up numbers, outside the app.

import "./style.css";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Phase = "downloading" | "retrying" | "installing" | "restarting" | "failed";

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
const retry = document.getElementById("update-retry") as HTMLButtonElement;

function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_048_576)} MB`;
}

/** How much is on disk, as the line under the bar says it. */
function sofar(p: Progress): string {
  return p.total ? `${megabytes(p.received)} of ${megabytes(p.total)}` : `${megabytes(p.received)} so far`;
}

function draw(p: Progress) {
  root.dataset.phase = p.phase;
  title.textContent = p.phase === "failed" ? "The update didn't install" : `Updating to Mycelium ${p.version}`;
  const share = p.total ? Math.min(1, p.received / p.total) : null;
  const moving = p.phase === "downloading" || p.phase === "retrying";
  // With no size given, the bar runs back and forth rather than guessing.
  bar.classList.toggle("indeterminate", p.phase === "downloading" && share === null);
  fill.style.width = moving ? `${Math.round((share ?? 0) * 100)}%` : "100%";
  if (share !== null) bar.setAttribute("aria-valuenow", String(Math.round(share * 100)));
  if (p.phase === "downloading") {
    line.textContent = p.received ? sofar(p) : "Starting the download…";
  } else if (p.phase === "retrying") {
    // What's on disk is kept, so the next try carries on from there.
    line.textContent = `Connection lost, retrying… ${sofar(p)}`;
  } else if (p.phase === "installing") {
    line.textContent = "Installing…";
  } else if (p.phase === "restarting") {
    line.textContent = "Restarting…";
  } else {
    line.textContent = p.error ?? "Something went wrong.";
  }
  note.textContent =
    p.phase === "failed"
      ? `You still have ${p.current}.`
      : "Mycelium restarts itself when it's ready. Your agents keep running in herdr.";
  retry.hidden = p.phase !== "failed";
  retry.disabled = false;
}

retry.addEventListener("click", () => {
  retry.disabled = true;
  void invoke("update_retry").catch((e) => {
    line.textContent = String(e);
    retry.disabled = false;
  });
});

const PREVIEW: Record<Phase, Progress> = {
  downloading: { version: "3.0.34", current: "3.0.33", phase: "downloading", received: 96_468_992, total: 251_658_240, error: null },
  retrying: { version: "3.0.34", current: "3.0.33", phase: "retrying", received: 96_468_992, total: 251_658_240, error: "The connection dropped" },
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
