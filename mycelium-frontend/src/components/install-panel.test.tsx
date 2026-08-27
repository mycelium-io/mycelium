// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CurrentUserProvider } from "@/components/current-user";
import { renderWithSWR } from "@/test/swr";
import { InstallPanel } from "@/components/install-panel";

/** The panel's only server read is the health probe. */
function stubHub(reachable: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      reachable ? new Response("{}", { status: 200 }) : Promise.reject(new Error("ECONNREFUSED")),
    ),
  );
}

function renderInstallPanel() {
  return renderWithSWR(
    <CurrentUserProvider>
      <InstallPanel />
    </CurrentUserProvider>,
  );
}

describe("<InstallPanel />", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("hands over one hub-aware terminal setup and says the hub is unreachable", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderInstallPanel();

    await user.click(screen.getByRole("button", { name: "Terminal" }));

    expect(screen.getByRole("button", { name: "Copy setup" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Hub unreachable"));
    // The honest framing: this isn't "not installed yet", it's down.
    expect(screen.getByText(/isn't answering right now/i)).toBeInTheDocument();
  });

  it("drops the unreachable note once the hub answers, keeping only the commands", async () => {
    const user = userEvent.setup();
    stubHub(true);
    renderInstallPanel();

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Hub reachable"));
    expect(screen.queryByText(/isn't answering right now/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Terminal" }));
    expect(screen.getByText(/Install, connect, and verify in one paste/i)).toBeInTheDocument();
  });

  it("shows a hub-aware coding-agent prompt by default", async () => {
    stubHub(false);
    renderInstallPanel();

    expect(screen.getByRole("button", { name: "Copy setup" })).toBeInTheDocument();
    expect(screen.getByText(/already have open/i)).toBeInTheDocument();
  });

  it("switches between the coding-agent and terminal handoffs", async () => {
    const user = userEvent.setup();
    stubHub(false);
    renderInstallPanel();

    const codingAgent = screen.getByRole("button", { name: "Coding agent" });
    const terminal = screen.getByRole("button", { name: "Terminal" });
    expect(codingAgent).toHaveAttribute("aria-pressed", "true");
    expect(terminal).toHaveAttribute("aria-pressed", "false");

    await user.click(terminal);
    expect(codingAgent).toHaveAttribute("aria-pressed", "false");
    expect(terminal).toHaveAttribute("aria-pressed", "true");
  });
});
