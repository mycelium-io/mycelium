// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { SearchPalette } from "@/components/search-palette";
import { Tooltip } from "@/components/ui/tooltip";
import { useKeyAction } from "@/components/keymap-provider";
import { searchEverything } from "@/lib/api";
import { isMacPlatform } from "@/lib/keymap";
import { resultHref, type SearchHit } from "@/lib/search";

const OpenSearchContext = createContext<(() => void) | null>(null);

/** Hosts the search surface and the `/` binding that opens it.
 *
 *  It lives in the app shell rather than in `KeymapProvider` because picking a
 *  result navigates, and the provider sits above the router. Registering the
 *  binding here rather than owning it in the provider also means the command
 *  palette lists "Search everything" through the ordinary path — a binding
 *  appears in ⌘K exactly where something has registered to handle it — which is
 *  what keeps `/` reachable from the composer, where bare keys are inert. */
export function GlobalSearch({ children }: { children?: ReactNode }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // Resolved after mount: the server has no platform to read, and a guess would
  // hydrate a ⌘ over a Ctrl.
  const [mac, setMac] = useState(false);
  useEffect(() => setMac(isMacPlatform()), []);

  const openSearch = useCallback(() => setOpen(true), []);
  useKeyAction("search.open", openSearch);

  const pick = useCallback(
    (hit: SearchHit) => {
      setOpen(false);
      router.push(resultHref(hit));
    },
    [router],
  );

  return (
    <OpenSearchContext.Provider value={openSearch}>
      {children}
      <SearchPalette
        open={open}
        onClose={() => setOpen(false)}
        onPick={pick}
        search={searchEverything}
        mac={mac}
      />
    </OpenSearchContext.Provider>
  );
}

/** The status-bar affordance that makes `/` findable without knowing it, next
 *  to the palette's and the cheatsheet's. */
export function GlobalSearchButton() {
  const openSearch = useContext(OpenSearchContext);
  if (!openSearch) return null;
  return (
    <Tooltip content="Search everything" side="top">
      <button
        type="button"
        onClick={openSearch}
        className="rounded px-1 text-micro text-muted-foreground transition-colors hover:text-text"
      >
        <kbd className="font-sans">/</kbd> search
      </button>
    </Tooltip>
  );
}
