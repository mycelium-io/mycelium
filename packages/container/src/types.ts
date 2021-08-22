export type ContainerProps<
  Tag extends React.Component<P> | keyof React.ReactHTML = any,
  E extends HTMLElement = HTMLElement,
  P extends any = {},
> = Partial<
  React.HTMLProps<E> &
    P & {
      tag: Tag
      vertical: boolean
      horizontal: boolean
      fullScreen: boolean
      center: boolean
      containerRef: React.Ref<E>
      testId?: string
    }
>
