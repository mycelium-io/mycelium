
import React from 'react'

import { Meta } from '@storybook/react'

import { Container } from '../src'

export default {
  component: Container,
  title: 'Components/Container',
} as Meta

export const Content: React.VFC<{}> = () => (
  <Container css={{ background: 'red' }}>Content</Container>
)

export const Vertical: React.VFC<{}> = () => (
  <Container css={{ height: 500 }} vertical>
    <div css={{ height: 1500 }}>Content</div>
  </Container>
)
