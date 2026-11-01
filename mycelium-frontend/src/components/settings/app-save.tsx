// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { CANCELLED } from "@/lib/desktop-app";
import { Note } from "./settings-ui";

/**
 * A change to the app's own settings: it runs `act`, says what went wrong if
 * it did, and stays quiet when the person said no on the machine. Most saves
 * restart what the app runs, and the app then shows how starting is going.
 */
export function useAppAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (act: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await act();
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (message !== CANCELLED) setError(message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

/** The Save that restarts the app, and what it costs, for a page's actions. */
export function RestartSave({ onSave, busy, disabled }: { onSave: () => void; busy: boolean; disabled?: boolean }) {
  return (
    <>
      <span className="hidden text-micro text-muted-foreground sm:inline">Mycelium restarts to save.</span>
      <Button size="sm" onClick={onSave} disabled={busy || disabled}>
        {busy ? "Saving…" : "Save"}
      </Button>
    </>
  );
}

export function ActionError({ error }: { error: string | null }) {
  return error ? <Note tone="error">{error}</Note> : null;
}
