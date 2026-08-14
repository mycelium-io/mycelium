// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  /** Optional CTA / hint rendered under the copy (a button, a code snippet). */
  action?: ReactNode;
  /** `sm` for narrow rails/panels, `md` for full-width areas. */
  size?: "sm" | "md";
  className?: string;
}

/** The one empty state for the whole app — consistent icon chip, title, copy.
 *  Full-pane usages (Channel, Negotiate, L9) pass `className="h-full"`; the copy
 *  stays top-aligned so it doesn't jump vertically as you switch between panes of
 *  differing height. Rail/list usages sit in flow near the top the same way. */
export function EmptyState({ icon: Icon, title, description, action, size = "md", className }: Props) {
  const sm = size === "sm";
  return (
    <div className={cn("flex flex-col items-center justify-start text-center", sm ? "px-4 py-10" : "px-8 py-16", className)}>
      {Icon && (
        <div
          className={cn(
            "mb-3 flex items-center justify-center rounded-xl bg-surface text-muted-foreground",
            sm ? "size-9" : "size-12",
          )}
        >
          <Icon className={sm ? "size-4" : "size-5"} strokeWidth={1.75} />
        </div>
      )}
      <div className={cn("font-medium text-text", sm ? "text-label" : "text-ui")}>{title}</div>
      {description && (
        <p className={cn("mt-1 max-w-xs leading-relaxed text-muted-foreground", sm ? "text-micro" : "text-label")}>
          {description}
        </p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
