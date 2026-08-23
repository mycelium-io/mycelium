// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";
import { InstallPanel } from "@/components/install-panel";
import { CLI_INSTALL_COMMAND, LOGIN_COMMAND, PROMPT_COMMAND, configSetCommand } from "@/lib/install";

/** The panel's only server read is the health probe. */
function stubHub(reachable: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      reachable ? new Response("{}", { status: 200 }) : Promise.reject(new Error("ECONNREFUSED")),
    ),
  );
}

/** The commands are read-only inputs, so they're findable by value. */
function commandField(value: string) {
  return screen.getByDisplayValue(value);
}

describe("<InstallPanel />", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("hands over the CLI, config, and login commands, and says the hub is unreachable", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderWithSWR(<InstallPanel />);

    // Prompt is the default tab; switch to a manual one to see the three steps.
    await user.click(screen.getByRole("button", { name: "macOS" }));

    expect(commandField(CLI_INSTALL_COMMAND)).toBeInTheDocument();
    await waitFor(() =>
      expect(commandField(configSetCommand(window.location.origin))).toBeInTheDocument(),
    );
    expect(commandField(LOGIN_COMMAND)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Hub unreachable"));
    // The honest framing: this isn't "not installed yet", it's down.
    expect(screen.getByText(/isn't answering right now/i)).toBeInTheDocument();
  });

  it("drops the unreachable note once the hub answers, keeping only the commands", async () => {
    const user = userEvent.setup();
    stubHub(true);
    renderWithSWR(<InstallPanel />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Hub reachable"));
    expect(screen.queryByText(/isn't answering right now/i)).not.toBeInTheDocument();

    // The install commands stay reachable — a second machine still needs them.
    await user.click(screen.getByRole("button", { name: "macOS" }));
    expect(commandField(CLI_INSTALL_COMMAND)).toBeInTheDocument();
  });

  it("shows the WSL note when Windows is selected", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderWithSWR(<InstallPanel />);

    expect(screen.queryByText(/WSL/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Windows" }));
    expect(screen.getByText(/Run both commands inside WSL/)).toBeInTheDocument();
  });

  it("shows the agent prompt by default, and the manual steps once an OS tab is picked", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderWithSWR(<InstallPanel />);

    expect(commandField(PROMPT_COMMAND)).toBeInTheDocument();
    expect(screen.queryByText("Install the CLI")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(CLI_INSTALL_COMMAND)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "macOS" }));
    expect(commandField(CLI_INSTALL_COMMAND)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(PROMPT_COMMAND)).not.toBeInTheDocument();
  });

  it("highlights one tab at a time, and drops into the detected OS when Prompt is switched off", async () => {
    const user = userEvent.setup();
    stubHub(false);
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    );
    renderWithSWR(<InstallPanel />);

    const prompt = screen.getByRole("button", { name: "Prompt" });
    const macos = screen.getByRole("button", { name: "macOS" });
    expect(prompt).toHaveAttribute("aria-pressed", "true");
    expect(macos).toHaveAttribute("aria-pressed", "false");

    // Switching Prompt off lands on the detected OS, and only that one.
    await user.click(prompt);
    await waitFor(() => expect(macos).toHaveAttribute("aria-pressed", "true"));
    expect(prompt).toHaveAttribute("aria-pressed", "false");
    expect(commandField(CLI_INSTALL_COMMAND)).toBeInTheDocument();
  });

  it("deselects Prompt when an OS tab is picked", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderWithSWR(<InstallPanel />);

    await user.click(screen.getByRole("button", { name: "Linux" }));

    expect(screen.getByRole("button", { name: "Prompt" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Linux" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "macOS" })).toHaveAttribute("aria-pressed", "false");
  });
});
