// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { MachinesScreen } from "@/components/machines-screen";
import { GlobalStatusItems } from "@/components/status-items";

export default function MachinesPage() {
  return (
    <AppShell activeRoom={null} title="Machines" statusLeft={<span>Machines</span>} statusRight={<GlobalStatusItems />}>
      <MachinesScreen />
    </AppShell>
  );
}
