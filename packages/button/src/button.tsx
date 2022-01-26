import React from 'react'
import * as Icons from '@mycelium/icons'
import { COLOR, ICON_SIZE, BUTTON_THEME } from '../../types'
import { Props, AnchorProps, ButtonProps, EnumSide } from './types'
import styles from './styles'

const { WHITE, INKDARK } = COLOR

const getThemeColor = (theme?: BUTTON_THEME, light?: boolean): COLOR => {
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

const getIconColor = (
  theme?: BUTTON_THEME,
  light?: boolean,
  iconColor?: COLOR,
): COLOR => iconColor || getThemeColor(theme, light)

const getIconSize = (small: boolean = false, iconSize?: ICON_SIZE): ICON_SIZE =>
  iconSize || (small ? ICON_SIZE.SMALL : ICON_SIZE.DEFAULT)

export const Button: React.FC<Props> = (props) => {
  const {
    theme = BUTTON_THEME.BASIC,
    iconPlacement = 'left',
    icon = '',
    disabled = false,
    loading = false,
    fullWidth = false,
    small = false,
    light = false,
    hideLabelWhileLoading = false,
    className,
    width,
    iconSize,
    iconColor,
    iconTitle,
    iconDesc,
    children,
    ...restProps
  } = props
  const useIconColor = getIconColor(theme, light, iconColor)
  const useIconSize = getIconSize(small, iconSize)
  const Icon = icon && Icons[upperFirst(icon)]
  const { Spinner } = Icons
  const buttonClassName = cx(styles.button, className, {
    [styles.buttonBasic]: theme === BUTTON_THEME.BASIC,
    [styles.buttonLink]: theme === BUTTON_THEME.LINK,
    [styles.buttonPrimary]: theme === BUTTON_THEME.PRIMARY,
    [styles.buttonSecondary]: theme === BUTTON_THEME.SECONDARY,
    [styles.buttonPrimaryLight]: theme === BUTTON_THEME.PRIMARY && light,
    [styles.buttonSecondaryLight]: theme === BUTTON_THEME.SECONDARY && light,
    [styles.isDisabled]: disabled,
    [styles.buttonFullWidth]: fullWidth,
    [styles.buttonSmall]: small,
  })
  const isIconWithLabel =
    children && (Icon || (loading && !hideLabelWhileLoading))
  const buttonLabelClassName = cx({
    [styles.buttonLinkText]: theme === BUTTON_THEME.LINK,
    [styles.labelPlacementLeft]:
      isIconWithLabel && iconPlacement === EnumSide.RIGHT,
    [styles.labelPlacementRight]:
      isIconWithLabel && iconPlacement === EnumSide.LEFT,
  })

  const useIcon = Icon && (
    <Icon
      color={useIconColor}
      width={useIconSize}
      height={useIconSize}
      title={iconTitle}
      desc={iconDesc}
    />
  )

  if ((props as AnchorProps).to) {
    const { to, ...anchorProps } = restProps as AnchorProps

    return (
      <a className={buttonClassName} href={to} {...anchorProps}>
        {useIcon}
        <span className={buttonLabelClassName}>{children}</span>
      </a>
    )
  }

  const { onRef, type, ...buttonProps } = restProps as ButtonProps

  return (
    <button
      ref={onRef}
      className={buttonClassName}
      disabled={disabled || loading}
      tabIndex={0}
      type={type || 'button'}
      style={{ width }}
      {...buttonProps}
    >
      <>
        {loading && (
          <Spinner
            color={useIconColor}
            width={useIconSize}
            height={useIconSize}
            title="Loading, please wait a moment"
          />
        )}
        {!loading && useIcon}
        {(!loading || !hideLabelWhileLoading) && (
          <span className={buttonLabelClassName}>{children}</span>
        )}
      </>
    </button>
  )
}
