// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { SearchIcon } from "lucide-react";

import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";

/** shadcn's `command` (cmdk), restyled onto the app's tokens: the stock recipe
 *  ships shadcn's own palette (`bg-popover`, `border-input`, `text-sm`), none of
 *  which this design system defines — see the token table in globals.css.
 *
 *  cmdk supplies the mechanics only: fuzzy scoring, group/item bookkeeping, and
 *  arrow/⌃n/⌃p navigation with the selection following the query. The dialog
 *  chrome is ours (`<CommandPalette />`), so cmdk's `Command.Dialog` — and the
 *  Radix dialog it pulls in, which this app doesn't otherwise use — stays out.
 *
 *  cmdk writes `data-selected="false"` on unselected items, so selected styling
 *  must test for the value, never the attribute's presence. */

function Command({ className, ...props }: React.ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn("flex size-full flex-col overflow-hidden text-text", className)}
      {...props}
    />
  );
}

function CommandInput({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div
      data-slot="command-input-wrapper"
      className="flex flex-shrink-0 items-center gap-2.5 border-b border-border px-4"
    >
      <SearchIcon className="size-4 flex-shrink-0 text-faint" />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          "h-12 w-full bg-transparent text-body text-text outline-none placeholder:text-muted-foreground disabled:opacity-50",
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn("max-h-[min(60vh,26rem)] scroll-py-2 overflow-y-auto overflow-x-hidden p-1.5 outline-none", className)}
      {...props}
    />
  );
}

function CommandEmpty({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Empty>) {
  return (
    <CommandPrimitive.Empty
      data-slot="command-empty"
      className={cn("py-8 text-center text-label text-muted-foreground", className)}
      {...props}
    />
  );
}

function CommandGroup({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn(
        "overflow-hidden pb-1 last:pb-0 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:pb-1 **:[[cmdk-group-heading]]:pt-2 **:[[cmdk-group-heading]]:text-micro **:[[cmdk-group-heading]]:font-semibold **:[[cmdk-group-heading]]:uppercase **:[[cmdk-group-heading]]:tracking-wide **:[[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandSeparator({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Separator>) {
  return (
    <CommandPrimitive.Separator
      data-slot="command-separator"
      className={cn("-mx-1.5 my-1 h-px bg-border", className)}
      {...props}
    />
  );
}

function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "group/command-item relative flex cursor-default select-none items-center gap-2.5 rounded-lg px-2 py-1.5 text-label text-muted-foreground outline-none",
        "data-[selected=true]:bg-surface data-[selected=true]:text-text",
        "data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

/** The chord an item answers to, drawn as the same keycap the cheatsheet and
 *  the status rail use — only pushed to the row's right edge and lit with the
 *  selection. */
function CommandShortcut({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <Kbd
      data-slot="command-shortcut"
      tone="muted"
      className={cn("ml-auto group-data-[selected=true]/command-item:text-text", className)}
      {...props}
    />
  );
}

export {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
};
