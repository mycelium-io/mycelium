// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** Browser principal: self-asserted user handle from localStorage. */
const STORAGE_KEY = "mycelium.principal";

interface CurrentUser {
  /** Bare user handle (lowercase), or "" when acting anonymously. */
  principal: string;
  setPrincipal: (handle: string) => void;
}

const CurrentUserContext = createContext<CurrentUser | null>(null);

function normalize(handle: string): string {
  return handle.trim().replace(/^@/, "").toLowerCase();
}

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipalState] = useState("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) setPrincipalState(saved);
  }, []);

  const value = useMemo<CurrentUser>(
    () => ({
      principal,
      setPrincipal: (handle: string) => {
        const next = normalize(handle);
        setPrincipalState(next);
        if (typeof window !== "undefined") {
          if (next) window.localStorage.setItem(STORAGE_KEY, next);
          else window.localStorage.removeItem(STORAGE_KEY);
        }
      },
    }),
    [principal],
  );

  return (
    <CurrentUserContext.Provider value={value}>
      {children}
    </CurrentUserContext.Provider>
  );
}

export function useCurrentUser(): CurrentUser {
  const ctx = useContext(CurrentUserContext);
  if (!ctx) {
    throw new Error("useCurrentUser must be used within a CurrentUserProvider");
  }
  return ctx;
}
