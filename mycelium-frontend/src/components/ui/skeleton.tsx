// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";

/** The one loading placeholder for the whole app: a pulsing block on the
 *  surface token. Size and compose into row/card shapes at the call site. */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface", className)}
      {...props}
    />
  );
}
