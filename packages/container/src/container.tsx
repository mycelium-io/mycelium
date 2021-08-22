import React from 'react'
import { container } from './styles'
import { ContainerProps } from './types'

export const Container: React.FC<ContainerProps> = ({
  children,
  vertical = false,
  horizontal = false,
  fullScreen = false,
  center = false,
  containerRef,
  tag: Tag = 'div',
  testId,
  ...props
}) => (
  <Tag
    css={container(center, vertical, horizontal, fullScreen)}
    ref={containerRef}
    {...(testId ? { 'data-testid': testId } : {})}
    {...props}
  >
    {children}
  </Tag>
)

Container.displayName = 'Container'
