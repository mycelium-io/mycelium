import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: "#050a12",
        surface: "#0c1524",
        border: "#162035",
        accent: "#38bdf8",
        muted: "#4a6080",
      },
    },
  },
  plugins: [],
};
export default config;
