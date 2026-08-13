// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type ChipVariant = "default" | "accent";

interface Props {
  children: ReactNode;
  variant?: ChipVariant;
  active?: boolean;
  onClick?: () => void;
  className?: string;
}

export function Chip({
  children,
  variant = "default",
  active = false,
  onClick,
  className,
}: Props) {
  const accent = variant === "accent";

  const styles = cn(
    "text-label font-medium rounded-full px-3 py-1 border transition-colors",
    accent ? "border-accent/30" : "border-border",
    active
      ? accent
        ? "bg-accent-soft text-accent"
        : "bg-surface text-text"
      : accent
        ? "text-accent hover:bg-accent-soft"
        : "text-muted-foreground hover:bg-surface",
    onClick && "cursor-pointer",
    className,
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={styles}>
        {children}
      </button>
    );
  }
  return <span className={cn(styles, "inline-block")}>{children}</span>;
}
