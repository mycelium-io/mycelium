import { COLOR, BUTTON_THEME } from '../../../types'
import { getThemeColor } from './getThemeColor'

export const getIconColor = (
  theme?: BUTTON_THEME,
  light?: boolean,
  iconColor?: COLOR,
): COLOR => iconColor || getThemeColor(theme, light)