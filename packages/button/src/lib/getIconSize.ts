import { ICON_SIZE } from '../../../types'

export const getIconSize = (small: boolean = false, iconSize?: ICON_SIZE): ICON_SIZE =>
  iconSize || (small ? ICON_SIZE.SMALL : ICON_SIZE.DEFAULT)