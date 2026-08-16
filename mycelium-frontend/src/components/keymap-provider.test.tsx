// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KeymapProvider, useKeyAction, useKeyScope } from "@/components/keymap-provider";

function Room({ onPane }: { onPane: (id: string) => void }) {
  useKeyScope("room");
  useKeyAction("pane.channel", () => onPane("channel"));
  useKeyAction("pane.plan", () => onPane("plan"));
  return null;
}

function Composer() {
  const [value, setValue] = useState("");
  return <textarea aria-label="Message" value={value} onChange={e => setValue(e.target.value)} />;
}

describe("<KeymapProvider />", () => {
  it("fires the action a leader sequence names", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

    await user.keyboard("gc");
    expect(onPane).toHaveBeenCalledWith("channel");

    await user.keyboard("gp");
    expect(onPane).toHaveBeenLastCalledWith("plan");
  });

  it("drops a sequence whose second chord names nothing", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

    await user.keyboard("gz");
    await user.keyboard("c");
    expect(onPane).not.toHaveBeenCalled();
  });

  it("leaves a room binding inert outside a room", async () => {
    const fired = vi.fn();
    const user = userEvent.setup();

    function Unscoped() {
      // Registered, but nothing declares the "room" scope live.
      useKeyAction("pane.channel", () => fired("channel"));
      useKeyAction("rooms.next", () => fired("next"));
      return null;
    }

    render(
      <KeymapProvider>
        <Unscoped />
      </KeymapProvider>,
    );

    await user.keyboard("gc");
    expect(fired).not.toHaveBeenCalled();

    await user.keyboard("]");
    expect(fired).toHaveBeenCalledWith("next");
  });

  it("never fires while a text input has focus, and Esc returns to command mode", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
        <Composer />
      </KeymapProvider>,
    );

    const box = screen.getByLabelText("Message");
    await user.click(box);
    await user.keyboard("go camping");
    expect(onPane).not.toHaveBeenCalled();
    expect(box).toHaveValue("go camping");
    expect(box).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(box).not.toHaveFocus();

    await user.keyboard("gc");
    expect(onPane).toHaveBeenCalledWith("channel");
  });

  it("opens the cheatsheet on ? and lists the bindings live in this context", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={vi.fn()} />
      </KeymapProvider>,
    );

    await user.keyboard("?");
    const sheet = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(sheet).toHaveTextContent("Channel");
    expect(sheet).toHaveTextContent("Next room");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
  });

  it("omits room bindings from the cheatsheet outside a room", async () => {
    const user = userEvent.setup();
    render(<KeymapProvider>{null}</KeymapProvider>);

    await user.keyboard("?");
    const sheet = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(sheet).toHaveTextContent("Next room");
    expect(sheet).not.toHaveTextContent("Write a message");
  });

  it("shows the pending leader while a sequence is half-typed", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={vi.fn()} />
      </KeymapProvider>,
    );

    await user.keyboard("g");
    expect(screen.getByRole("status")).toHaveTextContent("g…");
    await user.keyboard("c");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
