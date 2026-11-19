// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** An upload's bytes or its thumbnail, as the hub serves them through the UI:
 *  `/api/rooms/<room>/uploads/<name>/raw` and `…/thumb`. The room and name are
 *  URL-encoded, so neither holds a slash. */
const UPLOAD_IMAGE = /^\/api\/rooms\/[^/]+\/uploads\/[^/]+\/(raw|thumb)$/;

/**
 * Whether an image a member put in a message or memory loads in the reader's
 * app. Only a room upload does: its bytes or thumbnail, from this page's own
 * origin, with or without a query such as the desktop app's signature.
 *
 * An image from anywhere else is shown as a link instead. One from another
 * site would tell that site the reader's IP address and when they read the
 * message. Any other path on this origin is refused too, because every
 * reader's app would send it a GET, and some routes act on one.
 */
export function loadsHere(src: string, origin: string = globalThis.location?.origin ?? ""): boolean {
  if (!src || !origin) return false;
  try {
    const url = new URL(src, origin);
    return url.origin === origin && UPLOAD_IMAGE.test(url.pathname);
  } catch {
    return false;
  }
}
