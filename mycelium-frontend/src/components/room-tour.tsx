// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef } from "react";
import { startRoomTour, type NegotiationPhase, type TourDeps, type TourHandle } from "@/lib/tour";

interface Props extends TourDeps {
  /** Start the tour when this flips true (e.g. `?tour=1`). */
  active: boolean;
  /** Live negotiation phase, fed to the controller for convergence sync. */
  phase: NegotiationPhase;
}

/** Thin seam: starts the imperative tour controller and forwards the phase. */
export function RoomTour({ active, phase, setEditorView, setInspectorTab, onExit }: Props) {
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

  useEffect(() => {
    handleRef.current?.notifyPhase(phase);
  }, [phase]);

  return null;
}
