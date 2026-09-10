// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import path from "node:path";
import { defineConfig } from "vitest/config";

// Component tests for the room UI. jsdom + testing-library; the `@/`
// alias mirrors tsconfig so component imports resolve the same as in Next.
// JSX is transformed by Vite's default transform (React 19 automatic
// runtime) with no config needed, so no vite React plugin is needed for
// the test build. (Vite 8 moved off esbuild as its default transform
// engine — an explicit `esbuild.jsx`/`jsxImportSource` override here is
// silently ignored now, and doesn't even type-check without `esbuild`
// installed as a real dependency, since Vite no longer bundles it.)
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
