module.exports = {
  "stories": ['../packages/**/stories/*.stories.tsx'],
  "addons": [
    "@storybook/addon-links",
    "@storybook/addon-essentials",
    "postcss-flexbugs-fixes",
    "autoprefixer"
  ],
  typescript: {
    check: false,
    checkOptions: {},
    reactDocgen: 'react-docgen-typescript',
    reactDocgenTypescriptOptions: {
      shouldExtractLiteralValuesFromEnum: true,
      propFilter: (prop) => (prop.parent ? !/node_modules/.test(prop.parent.fileName) : true),
    },
  },
}
