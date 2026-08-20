// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, type RenderOptions } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactElement, ReactNode } from "react";

/**
 * A fresh SWR cache per render.
 *
 * The room data hooks (`@/lib/room-data`) share one cache in the app — that's
 * the point of them. In tests that sharing would leak across cases: the second
 * render of a component would paint the first case's fixtures. Mounting a
 * provider with its own `Map` scopes the cache — and SWR's in-flight dedup,
 * which hangs off it — to one render.
 */
export function SWRTestCache({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), revalidateOnFocus: false }}>
      {children}
    </SWRConfig>
  );
}

export function renderWithSWR(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: SWRTestCache, ...options });
}
