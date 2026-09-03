// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

/**
 * `tsc --noEmit` covers types; this config adds checks a type checker cannot
 * see — chiefly react-hooks, whose dependency-array checks catch stale
 * closures in the SWR and CodeMirror wiring.
 */
const config = [
  { ignores: [".next/**", "node_modules/**", "out/**", "next-env.d.ts"] },
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // Two react-hooks v7 rules that flag idioms used widely across the
      // components (seeding state from an effect, and the `ref.current =
      // latest` pattern for values read from stable callbacks). Left as
      // warnings rather than switched off, so the count is visible and new
      // code can be held to them.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
    },
  },
];

export default config;
