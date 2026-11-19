// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useImperativeHandle, useLayoutEffect, useRef, type ComponentProps, type Ref } from "react";

type Props = Omit<ComponentProps<"dialog">, "open" | "onClose" | "onCancel" | "ref"> & {
  /** Runs once the dialog has closed itself: Escape, the back gesture, a
   *  click on the backdrop, or a child calling `close()` on it. */
  onClose: () => void;
  /** Whether a click on the backdrop closes it. */
  lightDismiss?: boolean;
  ref?: Ref<HTMLDialogElement>;
};

/** The dim, blurred backdrop the app's prompts and palettes sit on, faded in
 *  unless the person asked for reduced motion. */
export const MODAL_BACKDROP =
  "backdrop:bg-black/30 backdrop:backdrop-blur-[2px] motion-safe:backdrop:animate-in motion-safe:backdrop:fade-in-0";

/** The press and the release both have to land outside the box, so a text
 *  selection dragged out of the dialog doesn't dismiss it. The position is
 *  tested rather than the target, because the dialog is also the target for
 *  its own padding. */
function outside(e: PointerEvent, dialog: HTMLDialogElement): boolean {
  const r = dialog.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}

/**
 * A native modal `<dialog>`, open for as long as it is mounted.
 *
 * `showModal()` puts it in the top layer, makes the page behind it inert and
 * keeps focus inside, and Escape closes it. On close the browser returns focus
 * to whatever had it before. The backdrop is the dialog's `::backdrop`, styled
 * with Tailwind's `backdrop:` variant.
 *
 * The parent still decides whether it is open: mount it to open it, unmount it
 * to close it. When the dialog closes itself, `onClose` tells the parent so.
 *
 * Light dismiss uses `closedby="any"`. Safari doesn't support it yet, and the
 * desktop app renders with Safari's engine, so a pointer check stands in there.
 *
 * Elements inside it with `data-autofocus` (or the dialog itself) take focus
 * on open. React's `autoFocus` runs before the dialog is shown, when nothing
 * in it can take focus yet.
 */
export function ModalDialog({ onClose, lightDismiss = true, ref, children, ...props }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useImperativeHandle(ref, () => dialogRef.current as HTMLDialogElement);

  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // A layout effect so the cleanup closes the dialog while it is still in the
  // document. Closing it there is what returns focus to the opener.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    const first = dialog.matches("[data-autofocus]")
      ? dialog
      : dialog.querySelector<HTMLElement>("[data-autofocus]");
    first?.focus();

    // The browser fires `close` a task after the dialog closes. One that
    // arrives once it is open again is stale (React's development mode closes
    // and reopens it on mount), so it's ignored.
    const closed = () => {
      if (!dialog.open) onCloseRef.current();
    };
    dialog.addEventListener("close", closed);

    let pressedOutside = false;
    const down = (e: PointerEvent) => {
      pressedOutside = outside(e, dialog);
    };
    const up = (e: PointerEvent) => {
      if (pressedOutside && outside(e, dialog)) dialog.close();
      pressedOutside = false;
    };
    const fallback = lightDismiss && !("closedBy" in HTMLDialogElement.prototype);
    if (fallback) {
      dialog.addEventListener("pointerdown", down);
      dialog.addEventListener("pointerup", up);
    }

    return () => {
      dialog.removeEventListener("close", closed);
      dialog.removeEventListener("pointerdown", down);
      dialog.removeEventListener("pointerup", up);
      if (dialog.open) dialog.close();
    };
  }, [lightDismiss]);

  return (
    <dialog ref={dialogRef} closedby={lightDismiss ? "any" : "closerequest"} {...props}>
      {children}
    </dialog>
  );
}
