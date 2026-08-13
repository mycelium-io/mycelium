import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// App button language: sentence-case sans labels, one solid accent primary,
// quiet neutral variants. Modest radius. The system register (mono, tracked)
// lives in badges/IDs, not in buttons.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md border whitespace-nowrap text-label font-medium transition-colors outline-none select-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-accent text-accent-fg hover:opacity-90",
        outline:
          "border-border text-text hover:bg-surface hover:border-border2",
        secondary:
          "border-transparent bg-surface text-text hover:bg-elevated",
        ghost:
          "border-transparent text-muted-foreground hover:text-text hover:bg-hairline",
        destructive:
          "border-transparent bg-red text-white hover:opacity-90",
        link: "border-transparent text-accent underline-offset-4 hover:underline",
      },
      size: {
        default: "h-8 px-3.5",
        xs: "h-6 px-2 text-micro",
        sm: "h-7 px-2.5",
        lg: "h-9 px-4",
        icon: "size-8",
        "icon-xs": "size-6",
        "icon-sm": "size-7",
        "icon-lg": "size-9",
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
