// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The machines this browser starts agents on: the one the desktop app runs
 * on (the app opens the page with `?machine=<runner id>`), and any added here
 * with the code `mycelium runner` prints. The machine lists show these alone,
 * so opening a hub never shows someone else's computer, folders or agents.
 *
 * This is what the page shows, not what keeps a machine safe: a machine's
 * runner asks the person there before it starts anything a hub sends it.
 */

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "mycelium.machines";
const CHANGED = "mycelium:machines";
const NONE: string[] = [];

function parse(raw: string | null): string[] {
  if (!raw) return NONE;
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : NONE;
  } catch {
    return NONE;
  }
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

let cachedRaw: string | null = null;
let cached: string[] = NONE;

function snapshot(): string[] {
  const raw = readRaw();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cached = parse(raw);
  }
  return cached;
}

function write(ids: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Storage blocked: the machine is shown until the page reloads.
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The runner ids this browser starts agents on. Empty while rendering on the server. */
export function useMyMachines(): string[] {
  return useSyncExternalStore(subscribe, snapshot, () => NONE);
}

export function addMachine(id: string): void {
  const clean = id.trim();
  if (!clean) return;
  const ids = snapshot();
  if (!ids.includes(clean)) write([...ids, clean]);
}

export function forgetMachine(id: string): void {
  write(snapshot().filter((m) => m !== id));
}

/** Take `?machine=` from the address once: remember it, and drop it from the URL. */
export function takeMachineFromUrl(): void {
  const url = new URL(window.location.href);
  const id = url.searchParams.get("machine");
  if (!id) return;
  addMachine(id);
  url.searchParams.delete("machine");
  window.history.replaceState(window.history.state, "", url.toString());
}
