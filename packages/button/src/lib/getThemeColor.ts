import { COLOR, BUTTON_THEME } from '../../../types'

const { WHITE, INKDARK } = COLOR

export const getThemeColor = (theme?: BUTTON_THEME, light?: boolean): COLOR.WHITE | COLOR.INKDARK => {
  if (light) {
    switch (theme) {
      case BUTTON_THEME.SECONDARY:
        return WHITE
      case BUTTON_THEME.PRIMARY:
        return INKDARK
    }
  }

  return theme === BUTTON_THEME.PRIMARY ? WHITE : INKDARK
}