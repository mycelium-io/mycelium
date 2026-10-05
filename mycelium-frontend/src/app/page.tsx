// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { HomeDashboard } from "@/components/home-dashboard";

export default function Home() {
  return (
    <AppShell
      activeRoom={null}
    >
      <HomeDashboard />
    </AppShell>
  );
}
