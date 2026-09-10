// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import path from "node:path";
import { defineConfig } from "vitest/config";

// Component tests for the room UI. jsdom + testing-library; the `@/`
// alias mirrors tsconfig so component imports resolve the same as in Next.
// Vite 8's default transform already handles JSX (React 19 automatic
// runtime) with no config — an explicit esbuild.jsx override is ignored
// now that esbuild isn't Vite's default transform engine.
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
