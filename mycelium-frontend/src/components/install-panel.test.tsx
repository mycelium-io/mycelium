// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";
import { InstallPanel } from "@/components/install-panel";
import { CLI_INSTALL_COMMAND, STACK_INSTALL_COMMAND } from "@/lib/install";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

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

  it("hands over both commands and says no hub is answering yet", async () => {
    stubHub(false);
    renderWithSWR(<InstallPanel />);

    expect(commandField(CLI_INSTALL_COMMAND)).toBeInTheDocument();
    expect(commandField(STACK_INSTALL_COMMAND)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No hub yet"));
    // The honest constraint, stated rather than implied.
    expect(screen.getByText(/browser can't run the install/i)).toBeInTheDocument();
    expect(screen.queryByText("Next: your first room")).not.toBeInTheDocument();
  });

  it("flips to connected and shows the next steps once the hub answers", async () => {
    stubHub(true);
    renderWithSWR(<InstallPanel />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Hub connected"));
    expect(screen.getByText("Next: your first room")).toBeInTheDocument();
    expect(commandField("mycelium room create my-project && mycelium room use my-project")).toBeInTheDocument();
    // The install commands stay on screen — a second machine still needs them.
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

  it("preselects the platform it detects", async () => {
    stubHub(false);
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    );
    renderWithSWR(<InstallPanel />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "macOS" })).toHaveAttribute("aria-pressed", "true"),
    );
  });
});
