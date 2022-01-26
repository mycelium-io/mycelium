import React from 'react'

export type Props = {
  className?: string
  title?: string
  desc?: string
  viewBox?: string
} & React.SVGProps<SVGSVGElement>

export const Svg: React.FC<Props> = ({
  className,
  title,
  desc,
  viewBox,
  children,
  ...restProps
}): JSX.Element => (
  <svg className={className} focusable="false" viewBox={viewBox} {...restProps}>
    {children}
    {(title || desc) && (
      <rect x="0" y="0" width="100%" height="100%" stroke="none" opacity="0">
        {title && <title>{title}</title>}
        {desc && <desc>{desc}</desc>}
      </rect>
    )}
  </svg>
)
