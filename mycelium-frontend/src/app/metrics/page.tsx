// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { MetricsScreen } from "@/components/metrics-screen";
import { GlobalStatusItems } from "@/components/status-items";

export default function MetricsPage() {
  return (
    <AppShell activeRoom={null} statusLeft={<span>Metrics</span>} statusRight={<GlobalStatusItems />}>
      <MetricsScreen />
    </AppShell>
  );
}
