const PRODUCTION = 'production'
const TEST = 'test'

export const __DEV__ = process.env.NODE_ENV !== PRODUCTION

export const __TEST__ = process.env.NODE_ENV === TEST