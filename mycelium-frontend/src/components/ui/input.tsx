import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "w-full min-w-0 bg-bg border border-border px-3 py-2",
        "font-mono text-label text-text placeholder:text-muted-foreground",
        "transition-colors outline-none",
        "hover:border-border2",
        "focus:border-accent focus-visible:border-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-[#f87171]",
        className
      )}
      {...props}
    />
  )
}

export { Input }
