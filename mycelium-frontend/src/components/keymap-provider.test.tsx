// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KeyBadge } from "@/components/key-badge";
import { KeymapProvider, useKeyAction, useKeyScope } from "@/components/keymap-provider";

function Room({ onPane }: { onPane: (id: string) => void }) {
  useKeyScope("room");
  useKeyAction("pane.channel", () => onPane("channel"));
  useKeyAction("pane.plan", () => onPane("plan"));
  return <KeyBadge action="pane.l9" />;
}

function Composer() {
  const [value, setValue] = useState("");
  return <textarea aria-label="Message" value={value} onChange={e => setValue(e.target.value)} />;
}

describe("<KeymapProvider />", () => {
  it("fires the action a modifier chord names", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

    await user.keyboard("{Alt>}c{/Alt}");
    expect(onPane).toHaveBeenCalledWith("channel");

    await user.keyboard("{Alt>}p{/Alt}");
    expect(onPane).toHaveBeenLastCalledWith("plan");
  });

  it("ignores the bare key without its modifier", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

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

    await user.keyboard("{Alt>}c{/Alt}");
    expect(fired).not.toHaveBeenCalled();

    await user.keyboard("]");
    expect(fired).toHaveBeenCalledWith("next");
  });

  it("reveals each target's key while the modifier is held, and hides it on release", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={vi.fn()} />
      </KeymapProvider>,
    );

    expect(document.querySelector("[data-key-badge]")).toBeNull();
    await user.keyboard("{Alt>}");
    expect(document.querySelector("[data-key-badge]")).toHaveTextContent("L");
    await user.keyboard("{/Alt}");
    expect(document.querySelector("[data-key-badge]")).toBeNull();
  });

  it("keeps the badges off while the composer has focus", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={vi.fn()} />
        <Composer />
      </KeymapProvider>,
    );

    await user.click(screen.getByLabelText("Message"));
    await user.keyboard("{Alt>}");
    expect(document.querySelector("[data-key-badge]")).toBeNull();
    await user.keyboard("{/Alt}");
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
    await user.keyboard("a chat message");
    expect(onPane).not.toHaveBeenCalled();
    expect(box).toHaveValue("a chat message");
    expect(box).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(box).not.toHaveFocus();

    await user.keyboard("{Alt>}c{/Alt}");
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

  it("stays inert behind an open dialog, even once focus has left it", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
        <div role="dialog" aria-label="Incoming agent request">
          <button type="button">Accept</button>
        </div>
      </KeymapProvider>,
    );

    // Focus is on document.body — a backdrop click, not a dismissal.
    await user.keyboard("{Alt>}c{/Alt}");
    expect(onPane).not.toHaveBeenCalled();
  });

  it("refuses to register outside a provider, rather than silently doing nothing", () => {
    // The shipping bug this guards: a page registering bindings while sitting
    // above the provider it registers into.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Room onPane={vi.fn()} />)).toThrow(/KeymapProvider/);
    quiet.mockRestore();
  });
});
