// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Whether an image a member put in a message or memory loads in the reader's
 * app. Only an image the app itself serves does: an upload to the room, which
 * comes from this page's own origin. An image from anywhere else is shown as a
 * link instead, because loading it would tell that site the reader's IP
 * address and when they read the message.
 */
export function loadsHere(src: string, origin: string = globalThis.location?.origin ?? ""): boolean {
  if (!src || !origin) return false;
  try {
    return new URL(src, origin).origin === origin;
  } catch {
    return false;
  }
}
