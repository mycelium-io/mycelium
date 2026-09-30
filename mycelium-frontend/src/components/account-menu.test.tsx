// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const network = vi.fn();
vi.mock("@/lib/room-data", () => ({
  useNetworkStatus: () => network(),
}));

import { AboutView } from "@/components/account-menu";

describe("<AboutView />", () => {
  it("shows the hub's release and links to its notes", () => {
    network.mockReturnValue({ network: { version: "3.0.14" }, loading: false });
    render(<AboutView />);

    expect(screen.getByText("v3.0.14")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Release notes/ })).toHaveAttribute(
      "href",
      "https://github.com/mycelium-io/mycelium/releases/tag/v3.0.14",
    );
    expect(screen.getByRole("link", { name: /Changelog/ })).toHaveAttribute("target", "_blank");
    // In a browser there is no app version to show.
    expect(screen.queryByText("Mac app")).toBeNull();
  });

  it("calls an unreleased hub a development build, not a placeholder version", () => {
    network.mockReturnValue({ network: { version: "0.1.0" }, loading: false });
    render(<AboutView />);

    expect(screen.getByText("development build")).toBeInTheDocument();
    expect(screen.queryByText("v0.1.0")).toBeNull();
    expect(screen.getByRole("link", { name: /Releases/ })).toHaveAttribute(
      "href",
      "https://github.com/mycelium-io/mycelium/releases",
    );
  });

  it("says when the hub can't be reached", () => {
    network.mockReturnValue({ network: null, loading: false });
    render(<AboutView />);
    expect(screen.getByText("unreachable")).toBeInTheDocument();
  });

  it("shows the Mac app's own version inside the app", () => {
    network.mockReturnValue({ network: { version: "3.0.14" }, loading: false });
    const ua = vi.spyOn(navigator, "userAgent", "get").mockReturnValue("WebKit MyceliumDesktop/3.0.12");
    render(<AboutView />);

    expect(screen.getByText("Mac app")).toBeInTheDocument();
    expect(screen.getByText("v3.0.12")).toBeInTheDocument();
    ua.mockRestore();
  });
});
