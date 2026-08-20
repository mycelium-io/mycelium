// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { InstallPanel } from "@/components/install-panel";
import { GlobalStatusItems } from "@/components/status-items";

/** The deep-linkable install route (`/install`), for the docs and README to
 *  point at — the same panel the dashboard shows when no hub is answering. */
export default function InstallPage() {
  return (
    <AppShell activeRoom={null} statusLeft={<span>Install</span>} statusRight={<GlobalStatusItems />}>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-8 py-10">
          <h1 className="text-2xl font-semibold text-text">Set up Mycelium</h1>
          <p className="mt-1 text-label text-muted-foreground">
            The app is the window; the CLI is the hub it looks into. Install it once and this page
            turns green.
          </p>
          <InstallPanel variant="page" className="mt-6" />
        </div>
      </div>
    </AppShell>
  );
}
