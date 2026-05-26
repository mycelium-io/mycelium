// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

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
    "caps-mono-sm px-3 py-1.5 border transition-colors",
    accent ? "border-accent/40" : "border-border",
    active
      ? accent
        ? "bg-accent/[0.12]"
        : "bg-paper"
      : "bg-transparent",
    accent ? "text-accent" : active ? "text-text" : "text-text2",
    onClick && "hover:bg-paper cursor-pointer",
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
