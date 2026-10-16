// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Runner } from "@/lib/api";
import { FolderPicker, insideRoots } from "./folder-picker";

const ROOT = "/Users/morgan/code";
const runner = { id: "mbp", label: "morgans-mbp", roots: [ROOT] } as unknown as Runner;

/** The app's bridge, as its own hub UI sees it: this Mac is `machine`. */
function inTheApp(machine: string, picked: string | null) {
  const invoke = vi.fn(async (command: string) => (command === "this_machine" ? machine : picked));
  (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke };
  return invoke;
}

afterEach(() => {
  delete (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe("insideRoots", () => {
  it("takes a root or a folder under one, and nothing that only starts like one", () => {
    expect(insideRoots(ROOT, [ROOT])).toBe(true);
    expect(insideRoots(`${ROOT}/shop`, [ROOT])).toBe(true);
    expect(insideRoots(`${ROOT}-old/shop`, [ROOT])).toBe(false);
    expect(insideRoots("/etc", [ROOT])).toBe(false);
  });
});

describe("FolderPicker", () => {
  it("shows nothing in a browser, where the path is typed", () => {
    const { container } = render(<FolderPicker runner={runner} value="" onPick={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing for an agent starting on another machine", async () => {
    const invoke = inTheApp("studio-mini", `${ROOT}/shop`);
    const { container } = render(<FolderPicker runner={runner} value="" onPick={() => {}} />);
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("this_machine"));
    expect(container).toBeEmptyDOMElement();
  });

  it("opens the Mac's folder dialog at the folder typed and picks what was chosen", async () => {
    const invoke = inTheApp("mbp", `${ROOT}/shop`);
    const onPick = vi.fn();
    render(<FolderPicker runner={runner} value={`${ROOT}/api`} onPick={onPick} />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(`${ROOT}/shop`));
    expect(invoke).toHaveBeenCalledWith("choose_agent_folder", { start: `${ROOT}/api` });
  });

  it("starts at the first allowed folder when the typed one isn't inside it", async () => {
    const invoke = inTheApp("mbp", null);
    render(<FolderPicker runner={runner} value="/tmp/x" onPick={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("choose_agent_folder", { start: ROOT }));
  });

  it("refuses a folder agents may not start in", async () => {
    inTheApp("mbp", "/Users/morgan/Desktop");
    const onPick = vi.fn();
    render(<FolderPicker runner={runner} value="" onPick={onPick} />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose…" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(`Pick a folder inside ${ROOT}.`);
    expect(onPick).not.toHaveBeenCalled();
  });
});
