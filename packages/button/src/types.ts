import React from 'react'
import { COLOR, ICON_SIZE, BUTTON_THEME } from '../../types'

export interface BaseProps {
  theme: BUTTON_THEME
  width: number | string
  disabled: boolean
  loading: boolean
  fullWidth: boolean
  small: boolean
  light: boolean
  className: string
  icon: string
  iconSize: ICON_SIZE
  iconColor: COLOR
  iconTitle: string
  iconDesc: string
  iconPlacement: 'left' | 'right'
  hideLabelWhileLoading: boolean
}

export interface AnchorProps
  extends Pick<
    React.HTMLProps<HTMLAnchorElement>,
    Exclude<keyof React.HTMLProps<HTMLAnchorElement>, ['className', 'disabled']>
  > {
  to: string
}

export interface ButtonProps
  extends Pick<
    React.HTMLProps<HTMLButtonElement>,
    Exclude<keyof React.HTMLProps<HTMLButtonElement>, ['className', 'disabled']>
  > {
  onRef?: React.LegacyRef<HTMLButtonElement>
  type?: React.ButtonHTMLAttributes<HTMLButtonElement>['type']
}

export type Props = Partial<BaseProps> & (AnchorProps | ButtonProps)

export enum EnumSide {
 RIGHT = 'right',
 LEFT = 'left'
}
