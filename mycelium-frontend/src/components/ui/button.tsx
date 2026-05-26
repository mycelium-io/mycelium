import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// Re-themed to the app's button language: caps-mono labels, accent-outline
// with a translucent fill that intensifies on hover (matches "+ NEW ROOM",
// the chat SEND button, etc.). Square-ish, no heavy radius.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-sm border whitespace-nowrap caps-mono-sm transition-colors outline-none select-none focus-visible:border-accent disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default:
          "border-accent/40 bg-accent/[0.06] text-accent hover:bg-accent/[0.12] hover:border-accent/60",
        outline:
          "border-border text-text2 hover:text-text hover:border-border2",
        secondary:
          "border-border bg-surface text-text2 hover:text-text hover:border-border2",
        ghost:
          "border-transparent text-muted hover:text-text hover:bg-white/[0.04]",
        destructive:
          "border-[#f87171]/40 text-[#f87171] hover:bg-[#f87171]/10 hover:border-[#f87171]/60",
        link: "border-transparent text-accent underline-offset-4 hover:underline",
      },
      size: {
        default: "h-7 px-3",
        xs: "h-5 px-1.5",
        sm: "h-6 px-2",
        lg: "h-8 px-4",
        icon: "size-7",
        "icon-xs": "size-5",
        "icon-sm": "size-6",
        "icon-lg": "size-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
