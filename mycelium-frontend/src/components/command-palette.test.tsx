// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useMemo, useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KeymapProvider, useCommands, useKeyAction, useKeyScope } from "@/components/keymap-provider";
import type { PaletteCommand } from "@/lib/commands";

/** A room: the scope that makes the room-only bindings live, plus a command of
 *  its own, which is how a real page contributes to the palette. */
function Room({ onPane, onInvite }: { onPane?: (id: string) => void; onInvite?: () => void }) {
  useKeyScope("room");
  useKeyAction("pane.channel", () => onPane?.("channel"));
  useKeyAction("pane.plan", () => onPane?.("plan"));
  const commands = useMemo<PaletteCommand[]>(
    () => [{ id: "engine.invite", title: "Invite an engine", group: "Inspector", run: () => onInvite?.() }],
    [onInvite],
  );
  useCommands(commands);
  return null;
}

function Rooms({ names }: { names: string[] }) {
  const commands = useMemo<PaletteCommand[]>(
    () => names.map(name => ({ id: `room:${name}`, title: name, group: "Rooms", run: () => {} })),
    [names],
  );
  useCommands(commands);
  return null;
}

const openPalette = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.keyboard("{Control>}k{/Control}");
  return screen.findByRole("dialog", { name: "Command palette" });
};

const rowNames = (palette: HTMLElement) =>
  within(palette)
    .getAllByRole("option")
    .map(row => row.textContent);

describe("<CommandPalette />", () => {
  beforeEach(() => localStorage.clear());

  it("opens on the palette chord and closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    expect(palette).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });

  it("lists a keymap binding as a command, showing the chord that would skip it", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    const row = within(palette).getByRole("option", { name: /Channel/ });
    expect(row).toHaveTextContent("Alt+C");
  });

  it("runs the keymap action behind a row, and closes", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    await user.click(within(palette).getByRole("option", { name: /Channel/ }));

    expect(onPane).toHaveBeenCalledWith("channel");
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });

  it("runs a registered command", async () => {
    const onInvite = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onInvite={onInvite} />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    await user.click(within(palette).getByRole("option", { name: "Invite an engine" }));
    expect(onInvite).toHaveBeenCalled();
  });

  it("narrows to a fuzzy match and runs the selection on Enter", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Rooms names={["pricing-model", "release-train", "ops"]} />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    await user.keyboard("rlstrn");
    expect(rowNames(palette)).toEqual(["release-train"]);

    await user.keyboard("{Enter}");
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });

  it("navigates the results with the arrow keys", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Rooms names={["alpha", "beta", "gamma"]} />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    const selected = () =>
      within(palette)
        .getAllByRole("option")
        .find(row => row.getAttribute("data-selected") === "true")?.textContent;

    expect(selected()).toBe("alpha");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(selected()).toBe("gamma");
    await user.keyboard("{ArrowUp}");
    expect(selected()).toBe("beta");
  });

  it("keeps a room's commands out of the palette once the room is gone", async () => {
    const user = userEvent.setup();

    function App() {
      const [inRoom, setInRoom] = useState(true);
      return (
        <KeymapProvider>
          {inRoom && <Room />}
          <button type="button" onClick={() => setInRoom(false)}>
            Leave
          </button>
        </KeymapProvider>
      );
    }
    render(<App />);

    let palette = await openPalette(user);
    expect(within(palette).getByRole("option", { name: "Invite an engine" })).toBeInTheDocument();
    expect(within(palette).getByRole("option", { name: /Channel/ })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Leave" }));

    palette = await openPalette(user);
    expect(within(palette).queryByRole("option", { name: "Invite an engine" })).not.toBeInTheDocument();
    expect(within(palette).queryByRole("option", { name: /Channel/ })).not.toBeInTheDocument();
  });

  it("leads with what was run last time it was open", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Rooms names={["alpha", "beta", "gamma"]} />
      </KeymapProvider>,
    );

    let palette = await openPalette(user);
    expect(rowNames(palette)[0]).toBe("alpha");
    await user.click(within(palette).getByRole("option", { name: "gamma" }));

    palette = await openPalette(user);
    expect(rowNames(palette)[0]).toBe("gamma");
    expect(within(palette).getByText("Recent")).toBeInTheDocument();
  });

  it("says so when nothing matches", async () => {
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Rooms names={["alpha"]} />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    await user.keyboard("zzzzzz");
    expect(within(palette).queryAllByRole("option")).toHaveLength(0);
    expect(palette).toHaveTextContent("No matching commands.");
  });

  it("opens from the composer, where the bare keys are inert", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
        <textarea aria-label="Message" />
      </KeymapProvider>,
    );

    const box = screen.getByLabelText("Message");
    await user.click(box);
    await user.keyboard("{Alt>}c{/Alt}");
    expect(onPane).not.toHaveBeenCalled();

    await user.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("hands focus to the command that wants it, rather than taking it back", async () => {
    const user = userEvent.setup();

    function App() {
      const commands = useMemo<PaletteCommand[]>(
        () => [
          {
            id: "focus.box",
            title: "Write a message",
            group: "Focus",
            run: () => screen.getByLabelText("Message").focus(),
          },
        ],
        [],
      );
      useCommands(commands);
      return <textarea aria-label="Message" />;
    }

    render(
      <KeymapProvider>
        <App />
      </KeymapProvider>,
    );

    const palette = await openPalette(user);
    await user.click(within(palette).getByRole("option", { name: "Write a message" }));
    await waitFor(() => expect(screen.getByLabelText("Message")).toHaveFocus());
  });

  it("leaves the app's keys inert while it's open", async () => {
    const onPane = vi.fn();
    const user = userEvent.setup();
    render(
      <KeymapProvider>
        <Room onPane={onPane} />
      </KeymapProvider>,
    );

    await openPalette(user);
    await user.keyboard("{Alt>}c{/Alt}");
    expect(onPane).not.toHaveBeenCalled();
  });
});
