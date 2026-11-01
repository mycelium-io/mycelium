// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { APP_DOWNLOADS, type AppDownload } from "@/lib/desktop";

const env: { download: AppDownload | null; desktop: boolean } = { download: null, desktop: false };

vi.mock("@/lib/desktop", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop")>()),
  useAppDownload: () => env.download,
  useIsDesktop: () => env.desktop,
}));

import { ConnectMachine } from "./runner-fields";

describe("<ConnectMachine />", () => {
  beforeEach(() => {
    env.download = APP_DOWNLOADS.Mac;
    env.desktop = false;
  });

  it.each(Object.values(APP_DOWNLOADS))("offers the app first in a browser on $platform", (download) => {
    env.download = download;
    render(<ConnectMachine />);
    expect(screen.getByRole("link", { name: `Get Mycelium for ${download.platform}` })).toHaveAttribute(
      "href",
      download.url,
    );
    expect(screen.getByText(/Or run this in a terminal/)).toBeInTheDocument();
  });

  it("inside the app, says this computer is connecting rather than to run a runner", () => {
    // The app runs this computer's runner, so `mycelium runner` there would
    // only say one is already running.
    env.desktop = true;
    render(<ConnectMachine />);
    expect(screen.queryByRole("link", { name: /Get Mycelium for/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Run this in a terminal/)).not.toBeInTheDocument();
    expect(screen.getByText(/is connecting$/)).toBeInTheDocument();
    expect(screen.getByText("mycelium login")).toBeInTheDocument();
  });

  it("leaves the app out on a system it doesn't run on", () => {
    env.download = null;
    render(<ConnectMachine />);
    expect(screen.queryByRole("link", { name: /Get Mycelium for/ })).not.toBeInTheDocument();
  });
});
