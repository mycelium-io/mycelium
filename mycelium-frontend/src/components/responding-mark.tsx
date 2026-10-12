// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A spore's life, one glyph a frame: a dot that swells to a ring, bursts into
 *  a star, and settles back to a dot. */
export const SPORE_FRAMES = ["·", "∙", "•", "∘", "○", "◌", "◍", "✺", "✹", "✸", "✷", "✶", "✦", "∗"] as const;

/** What a spore shows when motion is reduced. */
export const SPORE_STILL = "•";

const FRAME_MS = 110;

// Every spore on screen steps from one timer, which runs only while one is
// mounted, and writes its glyph straight to the element: several agents
// responding at once costs one interval and no React renders.
const spores = new Set<{ el: HTMLElement; offset: number }>();
let timer: ReturnType<typeof setInterval> | null = null;
let step = 0;

function tick() {
  step += 1;
  for (const s of spores) s.el.textContent = SPORE_FRAMES[(step + s.offset) % SPORE_FRAMES.length];
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/** The mark before "… is responding": a teal spore that grows and bursts while
 *  an agent works. Still, as a dot, when motion is reduced. `offset` staggers
 *  two rows so they don't beat in step. */
export function SporeMark({ offset = 0 }: { offset?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion()) return;
    const entry = { el, offset };
    spores.add(entry);
    el.textContent = SPORE_FRAMES[(step + offset) % SPORE_FRAMES.length];
    if (!timer) timer = setInterval(tick, FRAME_MS);
    return () => {
      spores.delete(entry);
      if (spores.size === 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, [offset]);
  return (
    <span
      ref={ref}
      aria-hidden
      data-testid="spore-mark"
      className="inline-block w-3.5 flex-shrink-0 text-center font-mono text-[13px] leading-none"
      style={{ color: "var(--accent)" }}
    >
      {SPORE_STILL}
    </span>
  );
}

/** Words with a soft light sweeping across them, for a line about work in
 *  progress. Plain text when motion is reduced (`.responding-shimmer`). */
export function Shimmer({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={`responding-shimmer ${className ?? ""}`}>{children}</span>;
}
