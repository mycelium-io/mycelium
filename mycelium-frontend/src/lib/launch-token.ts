// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The token from `read`, or `null` for an empty or failed read. */
export function readToken(read: () => string): string | null {
  try {
    const token = read().trim();
    return token || null;
  } catch {
    return null;
  }
}
