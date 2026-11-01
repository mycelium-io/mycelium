"use client"

import * as React from "react"
import { Menu as Primitive } from "@base-ui/react/menu"

import { cn } from "@/lib/utils"
import { itemClass, popupClass } from "@/components/ui/context-menu"

/**
 * A menu opened from a button: the right-click menu's look and keys (arrows
 * through the rows, Enter to pick, Esc to close), anchored to its trigger.
 */
function DropdownMenu(props: Primitive.Root.Props) {
  return <Primitive.Root data-slot="dropdown-menu" {...props} />
}

function DropdownMenuTrigger(props: Primitive.Trigger.Props) {
  return <Primitive.Trigger data-slot="dropdown-menu-trigger" {...props} />
}

function DropdownMenuContent({
  className,
  align = "end",
  ...props
}: Primitive.Popup.Props & { align?: Primitive.Positioner.Props["align"] }) {
  return (
    <Primitive.Portal>
      <Primitive.Positioner className="z-50" side="bottom" align={align} sideOffset={4}>
        <Primitive.Popup
          data-slot="dropdown-menu-content"
          className={cn(popupClass, "max-h-[min(24rem,var(--available-height))] overflow-y-auto", className)}
          {...props}
        />
      </Primitive.Positioner>
    </Primitive.Portal>
  )
}

function DropdownMenuItem({ className, ...props }: Primitive.Item.Props) {
  return <Primitive.Item data-slot="dropdown-menu-item" className={cn(itemClass, className)} {...props} />
}

export { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger }
