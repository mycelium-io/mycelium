// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { MachinesScreen } from "@/components/machines-screen";

export default function MachinesPage() {
  return (
    <AppShell activeRoom={null} title="Machines">
      <MachinesScreen />
    </AppShell>
  );
}
