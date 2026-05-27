// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";
import { MetricsScreen } from "@/components/metrics-screen";

const crumbs: Crumb[] = [{ label: "metrics" }];

export default function MetricsPage() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar activeTab="metrics" />
      <SubNav crumbs={crumbs} />
      <MetricsScreen />
    </div>
  );
}
