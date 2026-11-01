import * as React from "react"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"

const SIZES = {
  md: "rounded-lg py-2 pl-3 pr-8",
  sm: "h-8 rounded-md pl-2 pr-7",
  xs: "h-7 rounded-md pl-1.5 pr-6",
} as const

const CHEVRON = { md: "right-2.5", sm: "right-2", xs: "right-1.5" } as const

const VARIANTS = {
  // The app's other inputs: a hairline border that brightens on hover and
  // turns accent on focus.
  outline: "border border-border bg-bg hover:border-border2 focus:border-accent",
  // For a select set inside something that already draws the box, or in a
  // title: no border until it's pointed at.
  ghost: "border border-transparent bg-transparent hover:bg-surface focus:border-accent",
} as const

type SelectProps = Omit<React.ComponentProps<"select">, "size"> & {
  size?: keyof typeof SIZES
  variant?: keyof typeof VARIANTS
  /** Classes for the select itself; `className` sizes and places the whole control. */
  selectClassName?: string
}

/**
 * A native `<select>` in the app's look. `appearance-none` drops the
 * browser's own button (WebKit draws a shadow and gradient over our classes,
 * in Safari and the Mac app), and the chevron is ours.
 */
function Select({
  className,
  selectClassName,
  size = "sm",
  variant = "outline",
  children,
  ...props
}: SelectProps) {
  return (
    <span data-slot="select" className={cn("relative inline-flex min-w-0", className)}>
      <select
        className={cn(
          "w-full min-w-0 cursor-pointer appearance-none truncate text-label text-text",
          "shadow-none outline-none transition-colors",
          "disabled:cursor-not-allowed disabled:opacity-50",
          SIZES[size],
          VARIANTS[variant],
          selectClassName
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground",
          CHEVRON[size]
        )}
      />
    </span>
  )
}

export { Select }
