// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { readToken } from "@/lib/launch-token";

/** Read this launch's token from stdin, once, into this process's memory. */
export function takeLaunchToken(): void {
  if (process.env.MYCELIUM_UI_TOKEN_STDIN !== "1" || process.env.MYCELIUM_UI_TOKEN) return;
  const token = readToken(() => readFileSync(0, "utf8"));
  if (token) process.env.MYCELIUM_UI_TOKEN = token;
}
