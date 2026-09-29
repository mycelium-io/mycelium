"use client"

import * as React from "react"
import { ContextMenu as Primitive } from "@base-ui/react/context-menu"
import { Check, ChevronRight, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Kbd, KbdChord } from "@/components/ui/kbd"

/**
 * The right-click menu, one look everywhere it appears. A menu only gathers
 * what a row can already do (its hover buttons, its `…` menu, its keys), so
 * right-clicking is a faster way to the same actions, never the only way.
 *
 * `ContextMenuTrigger` renders its child in place (`render`), so wrapping a row
 * adds no element and changes no layout.
 */
function ContextMenu({ ...props }: Primitive.Root.Props) {
  return <Primitive.Root data-slot="context-menu" {...props} />
}

/** Text selected inside `el`, which a right-click there means to copy. */
function selectionWithin(el: Element): boolean {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.toString().trim()) return false
  return el.contains(selection.anchorNode) || el.contains(selection.focusNode)
}

function ContextMenuTrigger({
  children,
  ...props
}: Omit<Primitive.Trigger.Props, "render" | "children"> & { children: React.ReactElement }) {
  return (
    <Primitive.Trigger
      data-slot="context-menu-trigger"
      render={children}
      // Selected text keeps the browser's own menu, so Copy is where it
      // always is; our menu is for the row, not for a selection in it.
      onContextMenu={(event) => {
        if (selectionWithin(event.currentTarget)) event.preventBaseUIHandler()
      }}
      {...props}
    />
  )
}

const popupClass =
  "z-50 min-w-52 origin-[var(--transform-origin)] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg outline-none duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"

function ContextMenuContent({ className, ...props }: Primitive.Popup.Props) {
  return (
    <Primitive.Portal>
      <Primitive.Positioner className="z-50" sideOffset={2}>
        <Primitive.Popup data-slot="context-menu-content" className={cn(popupClass, className)} {...props} />
      </Primitive.Positioner>
    </Primitive.Portal>
  )
}

const itemClass =
  "flex w-full cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-label text-text outline-none data-highlighted:bg-hairline data-disabled:pointer-events-none data-disabled:opacity-50"

interface ItemProps extends Omit<Primitive.Item.Props, "children"> {
  children: React.ReactNode
  icon?: LucideIcon
  /** A keymap action whose chord is shown on the right, when one is bound. */
  action?: string
  /** A literal key to show on the right, for keys a view handles itself. */
  keys?: string
  /** Red, for deleting or removing. */
  destructive?: boolean
}

function ContextMenuItem({ children, icon: Icon, action, keys, destructive, className, ...props }: ItemProps) {
  return (
    <Primitive.Item
      data-slot="context-menu-item"
      className={cn(itemClass, destructive && "text-red data-highlighted:bg-red/10", className)}
      {...props}
    >
      {Icon ? <Icon className="size-3.5 shrink-0 text-muted-foreground" /> : <span className="w-3.5 shrink-0" />}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {action && <KbdChord size="xs" tone="muted" action={action} />}
      {keys && <Kbd size="xs" tone="muted">{keys}</Kbd>}
    </Primitive.Item>
  )
}

function ContextMenuSeparator({ className, ...props }: React.ComponentProps<typeof Primitive.Separator>) {
  return <Primitive.Separator className={cn("my-1 h-px bg-border", className)} {...props} />
}

function ContextMenuLabel({ className, ...props }: Primitive.GroupLabel.Props) {
  return (
    <Primitive.GroupLabel className={cn("px-2 pb-1 pt-1.5 text-micro font-medium text-faint", className)} {...props} />
  )
}

function ContextMenuGroup(props: Primitive.Group.Props) {
  return <Primitive.Group {...props} />
}

function ContextMenuRadioGroup(props: Primitive.RadioGroup.Props) {
  return <Primitive.RadioGroup {...props} />
}

function ContextMenuRadioItem({ children, className, ...props }: Primitive.RadioItem.Props) {
  return (
    <Primitive.RadioItem className={cn(itemClass, className)} {...props}>
      <span className="grid w-3.5 shrink-0 place-items-center">
        <Primitive.RadioItemIndicator>
          <Check className="size-3.5 text-accent" />
        </Primitive.RadioItemIndicator>
      </span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </Primitive.RadioItem>
  )
}

/** A nested menu: `label` opens `children` to the side. */
function ContextMenuSub({
  label,
  icon: Icon,
  children,
}: {
  label: React.ReactNode
  icon?: LucideIcon
  children: React.ReactNode
}) {
  return (
    <Primitive.SubmenuRoot>
      <Primitive.SubmenuTrigger className={cn(itemClass, "data-popup-open:bg-hairline")}>
        {Icon ? <Icon className="size-3.5 shrink-0 text-muted-foreground" /> : <span className="w-3.5 shrink-0" />}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronRight className="size-3.5 shrink-0 text-faint" />
      </Primitive.SubmenuTrigger>
      <Primitive.Portal>
        <Primitive.Positioner className="z-50" sideOffset={4} alignOffset={-4}>
          <Primitive.Popup className={popupClass}>{children}</Primitive.Popup>
        </Primitive.Positioner>
      </Primitive.Portal>
    </Primitive.SubmenuRoot>
  )
}

export {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuLabel,
  ContextMenuGroup,
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
  ContextMenuSub,
}
