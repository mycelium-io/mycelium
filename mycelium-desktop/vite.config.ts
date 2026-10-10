import { resolve } from "node:path";
import { defineConfig } from "vite";

// The app's own pages: the first-run and loading screen, the agents terminal,
// and an update's download. The room itself is the hub's UI, loaded into the
// main window.
export default defineConfig({
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: {
    target: "safari16",
    outDir: "dist",
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        terminal: resolve(__dirname, "terminal.html"),
        update: resolve(__dirname, "update.html"),
      },
    },
  },
});
