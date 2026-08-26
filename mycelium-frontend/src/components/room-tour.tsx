// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef } from "react";
import { startRoomTour, type TourDeps, type TourHandle } from "@/lib/tour";

interface Props extends TourDeps {
  /** Start the tour when this flips true (e.g. `?tour=1`). */
  active: boolean;
}

/** Thin seam: starts the imperative tour controller. */
export function RoomTour({ active, setEditorView, setInspectorTab, onExit }: Props) {
  const handleRef = useRef<TourHandle | null>(null);

  useEffect(() => {
    if (!active) return;
    handleRef.current = startRoomTour({ setEditorView, setInspectorTab, onExit });
    return () => {
      handleRef.current?.destroy();
      handleRef.current = null;
    };
    // Start once per activation; deps are read fresh via the closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return null;
}
