import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { Container } from './index'

export default {
  title: 'Example/Container',
  component: Container,
  argTypes: {
    backgroundColor: { control: 'color' },
  },
} as ComponentMeta<typeof Container>

const Template: ComponentStory<typeof Container> = ({ childCss, ...args }) => (
  <Container {...args}>
    <div style={childCss}>
      Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod
      tempor incididunt ut labore et dolore magna aliqua.
    </div>
  </Container>
)

export const Vertical = Template.bind({})
Vertical.args = {
  childCss: { height: 2000 },
  vertical: true,
  css: { height: 550, width: '100%', border: '1px solid black' },
}

export const Horizontal = Template.bind({})
Horizontal.args = {
  childCss: { width: 2000 },
  horizontal: true,
  css: { height: 550, width: '100%', border: '1px solid black' },
  tag: 'section',
}

export const FullScreen = Template.bind({})
FullScreen.args = {
  fullScreen: true,
  css: { border: '1px solid black' },
}

export const Center = Template.bind({})
Center.args = {
  childCss: { height: 200 },
  center: true,
  css: { border: '1px solid black', width: 500 },
}
