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

/** `blob` as a PNG, the one image type browsers put on the clipboard: a PNG
 *  as it is, anything else (JPEG, WebP, GIF's first frame) redrawn on a canvas. */
export async function toPng(blob: Blob): Promise<Blob> {
  if (blob.type === "image/png") return blob;
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const g = canvas.getContext("2d");
  if (!g) throw new Error("This browser can't draw the image to copy it.");
  g.drawImage(bitmap, 0, 0);
  bitmap.close();
  return await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((png) => (png ? resolve(png) : reject(new Error("The image couldn't be turned into a PNG."))), "image/png"),
  );
}

/**
 * Put the image at `url` on the clipboard, as a PNG, so it pastes into
 * another app or back into a message. Rejects, with what to tell the person,
 * when it can't.
 *
 * The clipboard item is made at once, from a promise of the PNG, rather than
 * after the download: Safari only writes from within the click that asked,
 * and fetching first would end that.
 */
export async function copyImage(url: string): Promise<void> {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) {
    throw new Error("This browser can't copy images. Download it instead.");
  }
  const png = fetch(url)
    .then((res) => {
      if (!res.ok) throw new Error("The image couldn't be loaded to copy.");
      return res.blob();
    })
    .then(toPng);
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  } catch (err) {
    // The PNG's own failure says more than the clipboard's.
    await png;
    throw err instanceof Error && err.name === "NotAllowedError"
      ? new Error("The browser didn't allow copying the image.")
      : err;
  }
}
