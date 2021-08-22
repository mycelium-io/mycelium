import { css } from '@emotion/react'

const centerStyle = css({
  left: '50%',
  top: '50%',
  width: 'fit-content',
  display: 'inline-block',
  transform: 'translate(-50%, -50%)',
  '@media (max-width: 420px)': {
    width: '100%',
  },
  '::marker': {
    display: 'none',
  },
})

const scrollY = css({
  overflowY: 'scroll',
})

const scrollX = css({
  overflowX: 'scroll',
})

const fullscreenContainer = css({
  position: 'absolute',
  top: 0,
  bottom: 0,
  right: 0,
  left: 0,
})

export const container = (
  center: boolean,
  vertical: boolean,
  horizontal: boolean,
  fullScreen: boolean,
) =>
  css(
    {
      position: 'relative',
    },
    center && centerStyle,
    vertical && scrollY,
    horizontal && scrollX,
    fullScreen && fullscreenContainer,
  )
