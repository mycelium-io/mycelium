// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { HomeDashboard } from "@/components/home-dashboard";
import { GlobalStatusItems } from "@/components/status-items";

export default function Home() {
  return (
    <AppShell
      activeRoom={null}
      statusLeft={<span>Home</span>}
      statusRight={<GlobalStatusItems />}
    >
      <HomeDashboard />
    </AppShell>
  );
}
