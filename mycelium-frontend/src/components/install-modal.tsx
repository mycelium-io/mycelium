// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { InstallPanel } from "@/components/install-panel";

const OpenInstallModalContext = createContext<(() => void) | null>(null);

/** Opens the shared "Install the CLI" modal from anywhere under an `AppShell`. */
export function useOpenInstallModal(): () => void {
  const open = useContext(OpenInstallModalContext);
  if (!open) throw new Error("useOpenInstallModal must be used within InstallModalProvider");
  return open;
}

/** Hosts the install modal once for the whole shell, so the header button, the
 *  command palette, and any in-page link all trigger the same dialog instance. */
export function InstallModalProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <OpenInstallModalContext.Provider value={() => setOpen(true)}>
      {children}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogTitle className="sr-only">Install the CLI</DialogTitle>
          <DialogDescription className="sr-only">Guided setup to connect the CLI to this hub.</DialogDescription>
          <InstallPanel />
        </DialogContent>
      </Dialog>
    </OpenInstallModalContext.Provider>
  );
}
