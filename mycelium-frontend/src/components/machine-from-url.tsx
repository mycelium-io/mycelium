// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect } from "react";
import { takeMachineFromUrl } from "@/lib/my-machines";

/**
 * The desktop app opens the page with `?machine=<its runner id>`: remember
 * that machine as this browser's, whichever page it lands on.
 */
export function MachineFromUrl() {
  useEffect(() => {
    takeMachineFromUrl();
  }, []);
  return null;
}
