// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type Ref,
  type TextareaHTMLAttributes,
} from "react";
import TextareaAutosize from "react-textarea-autosize";
import { cn } from "@/lib/utils";

/** True when the browser grows a text box to fit its text from CSS alone. */
export function supportsFieldSizing(): boolean {
  return typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("field-sizing", "content");
}

const noSubscribe = () => () => {};

const FRAME = ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"] as const;

/** The vertical padding and border of a box, in pixels. */
function frameOf(el: HTMLElement): number {
  const s = getComputedStyle(el);
  return FRAME.reduce((sum, k) => sum + (parseFloat(s[k]) || 0), 0);
}

/**
 * A box scrolls only once it has grown to its cap, judged by the height it was
 * given rather than by how its text measures. WebKit (the desktop app on a Mac)
 * can measure a box a fraction short of its text, by more than a pixel when the
 * page is zoomed out, and would otherwise draw a scrollbar for nothing.
 */
function atCap(el: HTMLTextAreaElement, height: number, cap: number): boolean {
  return height >= cap - 1 && el.scrollHeight > el.clientHeight + 1;
}

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "style" | "rows"> & {
  ref?: Ref<HTMLTextAreaElement>;
  /** How many lines tall the box is when empty. */
  minRows: number;
  /** How many lines tall the box grows before its text scrolls. */
  maxRows: number;
  /** Called with true when the box reaches `maxRows` and its text scrolls, and false when it fits again. */
  onScrollsChange?: (scrolls: boolean) => void;
};

/**
 * A text box that grows with its text between `minRows` and `maxRows` lines.
 * Where the browser supports `field-sizing: content`, CSS does the growing.
 * Elsewhere `react-textarea-autosize` measures the text and sets the height.
 */
export function GrowTextarea({ ref, minRows, maxRows, onScrollsChange, className, ...props }: Props) {
  // The server can't know what the browser supports, so the first render after
  // a page load measures, and the box switches to CSS once the page is live.
  const native = useSyncExternalStore(noSubscribe, supportsFieldSizing, () => false);
  const own = useRef<HTMLTextAreaElement | null>(null);
  const [scrolls, setScrolls] = useState(false);
  const [frame, setFrame] = useState<number | null>(null);

  const setRef = useCallback(
    (el: HTMLTextAreaElement | null) => {
      own.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [ref],
  );

  const scrollsNow = useRef(false);
  const report = useCallback(
    (next: boolean) => {
      if (scrollsNow.current === next) return;
      scrollsNow.current = next;
      setScrolls(next);
      onScrollsChange?.(next);
    },
    [onScrollsChange],
  );

  // With CSS doing the growing, the box is checked against its max height when
  // its size or its text changes. Text past the cap changes no size, so the
  // text is watched too.
  const check = useCallback(() => {
    const el = own.current;
    if (!el) return;
    report(atCap(el, el.offsetHeight, parseFloat(getComputedStyle(el).maxHeight)));
  }, [report]);

  useLayoutEffect(() => {
    const el = own.current;
    if (native && el) setFrame(frameOf(el));
  }, [native]);

  useLayoutEffect(() => {
    if (native && frame !== null) check();
  }, [native, frame, check, props.value]);

  useLayoutEffect(() => {
    const el = own.current;
    if (!native || !el) return;
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [native, check]);

  const overflowY = scrolls ? "auto" : "hidden";

  if (native) {
    return (
      <textarea
        ref={setRef}
        {...props}
        style={{
          overflowY,
          ...(frame !== null && {
            minHeight: `calc(${minRows}lh + ${frame}px)`,
            maxHeight: `calc(${maxRows}lh + ${frame}px)`,
          }),
        }}
        className={cn("[field-sizing:content]", className)}
      />
    );
  }

  return (
    <TextareaAutosize
      ref={setRef}
      {...props}
      minRows={minRows}
      maxRows={maxRows}
      onHeightChange={(height, { rowHeight }) => {
        const el = own.current;
        if (el) report(atCap(el, height, rowHeight * maxRows + frameOf(el)));
      }}
      style={{ overflowY }}
      className={className}
    />
  );
}
