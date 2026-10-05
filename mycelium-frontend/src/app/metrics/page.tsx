// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AppShell } from "@/components/app-shell";
import { MetricsScreen } from "@/components/metrics-screen";

export default function MetricsPage() {
  return (
    <AppShell activeRoom={null} title="Metrics">
      <MetricsScreen />
    </AppShell>
  );
}
