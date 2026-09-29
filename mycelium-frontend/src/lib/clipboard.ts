// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Copy text, quietly doing nothing where the clipboard is blocked. */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Blocked (an insecure origin, a denied permission): the text is still on
    // screen to select by hand.
  }
}

/** An app path as a full link on this hub, for pasting somewhere else. */
export function absoluteUrl(path: string): string {
  return new URL(path, window.location.origin).toString();
}
