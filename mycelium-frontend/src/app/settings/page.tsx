// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Suspense } from "react";
import { AppShell } from "@/components/app-shell";
import { SettingsScreen } from "@/components/settings/settings-screen";

/** Settings opens on General; each page has its own address under it. */
export default function SettingsPage() {
  return (
    <AppShell activeRoom={null} title="Settings">
      <Suspense>
        <SettingsScreen page="general" />
      </Suspense>
    </AppShell>
  );
}
