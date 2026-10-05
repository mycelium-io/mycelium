// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { HubSettingsScreen } from "@/components/hub-settings-screen";

export default function SettingsPage() {
  return (
    <AppShell activeRoom={null} title="Settings">
      <HubSettingsScreen />
    </AppShell>
  );
}
