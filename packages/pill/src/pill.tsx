import React, { ReactNode } from 'react'
import cx from 'classnames'
import { Container, Props as ContainerProps } from '@mycelium/container
import { Text, Transform } from '../Text'
import styles from './styles.module.scss'

export type Props = Omit<
  ContainerProps<
    'div',
    HTMLDivElement,
    {
      type?: 'blocked' | 'locked' | 'active' | 'success' | 'pending' | string
      transform?: Transform
      className?: string
      title?: string
    }
  >,
  'label'
> & {
  label?: ReactNode
}

export const Pill: React.FC<Props> = ({
  type = null,
  label = '',
  transform = Transform.CAPS,
  className,
  title,
  ...restProps
}) => {
  const pillClass = cx(
    styles.pill,
    {
      [styles[type!]]: Boolean(type),
    },
    className,
  )

  return (
    <Container
      title={title || (typeof label === 'string' && label) || ''}
      className={pillClass}
      {...restProps}
    >
      {typeof label === 'string' ? (
        <Text transform={transform}>{label}</Text>
      ) : (
        label
      )}
    </Container>
  )
}
