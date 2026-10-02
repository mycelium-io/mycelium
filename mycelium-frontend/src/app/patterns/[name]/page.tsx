// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useParams } from "next/navigation";
import { PatternExplorer } from "@/components/patterns/pattern-explorer";

/** The patterns explorer, opened on one pattern. */
export default function PatternPage() {
  const params = useParams<{ name: string }>();
  return <PatternExplorer name={params.name ? decodeURIComponent(params.name) : null} />;
}
