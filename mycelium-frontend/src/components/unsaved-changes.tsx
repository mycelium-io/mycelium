// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export interface UnsavedGuard {
  /** Report whether the editor currently holds unsaved edits. */
  setDirty: (dirty: boolean) => void;
  /** Run `action` now if nothing is unsaved, else ask before discarding. */
  guard: (action: () => void) => void;
  /** Render this somewhere in the host's tree for the prompt to appear. */
  dialog: ReactNode;
}

/**
 * Guards navigation away from an editor that holds unsaved edits.
 *
 * The host reports edit state through `setDirty` and routes anything that
 * would unmount or replace the editor through `guard`, which either runs the
 * action straight away or holds it until the prompt is answered.
 *
 * Closing or reloading the tab is covered by the browser's own prompt. In-app
 * navigation that bypasses `guard` — a `<Link>`, or the back button — is not:
 * the App Router has no supported way to intercept it.
 */
export function useUnsavedGuard(): UnsavedGuard {
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const guard = useCallback(
    (action: () => void) => {
      if (!dirty) {
        action();
        return;
      }
      // Stored via an updater so React keeps the function instead of calling it.
      setPending(() => action);
    },
    [dirty],
  );

  const discard = useCallback(() => {
    pending?.();
    setPending(null);
    setDirty(false);
  }, [pending]);

  const dialog = (
    <Dialog open={pending !== null} onOpenChange={open => !open && setPending(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Discard unsaved changes?</DialogTitle>
          <DialogDescription>
            This memory has edits that have not been saved. Leaving now loses them.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setPending(null)}>
            Keep editing
          </Button>
          <Button onClick={discard}>Discard</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

  return { setDirty, guard, dialog };
}
