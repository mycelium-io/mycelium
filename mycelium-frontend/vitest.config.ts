// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import path from "node:path";
import { defineConfig } from "vitest/config";

// Component tests for the room UI. jsdom + testing-library; the `@/`
// alias mirrors tsconfig so component imports resolve the same as in Next.
// JSX is transformed by vitest's built-in esbuild (React 19 automatic runtime),
// so no vite React plugin is needed for the test build.
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
