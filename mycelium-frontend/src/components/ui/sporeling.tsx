// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { AVATAR_FILL, AVATAR_INK } from "@/lib/avatar-color";
import { genome, type Detail, type Genome } from "@/lib/sporelings";

/** The creature's three colors, all from the handle's avatar tint:
 *
 *  - `ink`: the creature's main shape, the same color the initials were (the tint
 *    mixed with the theme's text color), so it holds the initials' 4.5:1 against
 *    the disc in both themes.
 *  - `mid`: a second, softer shape (a cap's face, an owl's ears), halfway to the disc.
 *  - `hole`: the disc's own color, for eyes and markings, which read as cut out
 *    of the body rather than drawn on it, so they keep the same contrast. */
function palette(tint: string) {
  return {
    ink: `color-mix(in srgb, ${tint} ${AVATAR_INK}%, var(--text))`,
    mid: `color-mix(in srgb, ${tint} 62%, var(--text))`,
    hole: `color-mix(in srgb, ${tint} ${AVATAR_FILL}%, var(--surface))`,
  };
}
type Palette = ReturnType<typeof palette>;

/** Two eyes, cut out of the body. A glyph's are a little bigger, to survive 20px. */
function Eyes({ cx, cy, gap, r, glyph, c }: { cx: number; cy: number; gap: number; r: number; glyph: boolean; c: Palette }) {
  return (
    <>
      {[cx - gap / 2, cx + gap / 2].map((x) => (
        <circle key={x} cx={x} cy={cy} r={glyph ? r * 1.35 : r} style={{ fill: c.hole }} />
      ))}
    </>
  );
}

function Creature({ g, c, glyph }: { g: Genome; c: Palette; glyph: boolean }) {
  const gap = (n: number) => n * g.eyeGap;
  switch (g.family) {
    case "cap": {
      const cap = {
        dome: "M8 54 Q12 8 50 6 Q88 8 92 54 Q50 64 8 54Z",
        cone: "M10 54 Q28 30 50 -2 Q72 30 90 54 Q50 64 10 54Z",
        flat: "M2 50 Q18 18 50 16 Q82 18 98 50 Q50 62 2 50Z",
        bell: "M14 56 Q10 20 50 8 Q90 20 86 56 Q50 66 14 56Z",
      }[g.cap];
      const spots = [
        [32, 30],
        [60, 24],
        [72, 40],
        [44, 42],
      ].slice(0, g.spots);
      return (
        <>
          <ellipse cx="50" cy="70" rx="22" ry="20" style={{ fill: c.ink }} />
          <path d={cap} style={{ fill: c.mid }} />
          {!glyph && spots.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="5" style={{ fill: c.ink }} />)}
          <Eyes cx={50} cy={72} gap={gap(18)} r={5} glyph={glyph} c={c} />
        </>
      );
    }
    case "owl":
      return (
        <>
          {g.tufts === "ears" && <path d="M18 40 L14 4 L40 24Z M82 40 L86 4 L60 24Z" style={{ fill: c.mid }} />}
          {g.tufts === "crest" && (
            <path d="M42 26 Q40 6 46 0 M50 24 Q50 4 54 -2 M58 26 Q62 8 66 2" style={{ stroke: c.mid, fill: "none" }} strokeWidth="6" strokeLinecap="round" />
          )}
          <circle cx="50" cy="56" r="34" style={{ fill: c.ink }} />
          {!glyph && <ellipse cx="50" cy="76" rx="16" ry="11" style={{ fill: c.mid }} />}
          <Eyes cx={50} cy={50} gap={gap(30)} r={8} glyph={glyph} c={c} />
          <path d="M45 60 L55 60 L50 70Z" style={{ fill: "#e0a243" }} />
        </>
      );
    case "moth":
      return (
        <>
          <path d="M40 30 Q30 8 16 2 M60 30 Q70 8 84 2" style={{ stroke: c.mid, fill: "none" }} strokeWidth="6" strokeLinecap="round" />
          {!glyph && <path d="M50 58 Q6 30 4 60 Q8 86 50 70Z M50 58 Q94 30 96 60 Q92 86 50 70Z" style={{ fill: c.mid }} />}
          <circle cx="50" cy="58" r="32" style={{ fill: c.ink }} />
          <Eyes cx={50} cy={56} gap={gap(26)} r={6} glyph={glyph} c={c} />
        </>
      );
    case "slime":
      return (
        <>
          <path d="M12 92 Q8 34 50 14 Q92 34 88 92Z" style={{ fill: c.ink }} />
          {!glyph && <ellipse cx="36" cy="36" rx="8" ry="4" transform="rotate(-30 36 36)" style={{ fill: c.hole, opacity: 0.6 }} />}
          <Eyes cx={50} cy={58} gap={gap(26)} r={6} glyph={glyph} c={c} />
        </>
      );
    case "snail":
      return (
        <>
          <path d="M30 70 L26 16 M42 66 L44 14" style={{ stroke: c.ink, fill: "none" }} strokeWidth="6" strokeLinecap="round" />
          <circle cx="26" cy="14" r={glyph ? 7 : 5.5} style={{ fill: c.ink }} />
          <circle cx="44" cy="12" r={glyph ? 7 : 5.5} style={{ fill: c.ink }} />
          <path d="M2 94 Q6 66 40 66 L98 94Z" style={{ fill: c.mid }} />
          <circle cx="62" cy="54" r="30" style={{ fill: c.ink }} />
          <path d="M62 54 m-6 0 a6 6 0 1 1 12 0 a12 12 0 1 1 -24 0" style={{ stroke: c.hole, fill: "none" }} strokeWidth={glyph ? 6 : 5} />
        </>
      );
    case "lantern":
      return (
        <>
          <circle cx="50" cy="44" r="46" style={{ fill: c.ink, opacity: 0.18 }} />
          <path d="M44 66 Q42 92 50 96 Q58 92 56 66Z" style={{ fill: c.mid }} />
          <path d="M8 58 Q8 8 50 6 Q92 8 92 58 Q50 70 8 58Z" style={{ fill: c.ink }} />
          <Eyes cx={50} cy={42} gap={gap(22)} r={5} glyph={glyph} c={c} />
        </>
      );
  }
}

/** One agent's creature, drawn into the avatar's circle. The circle, its tint,
 *  the presence ring and the corner dot all stay with `Monogram`; this is only
 *  what sits inside, in place of the initials. */
export function Sporeling({ handle, tint, detail, engine = false }: { handle: string; tint: string; detail: Detail; engine?: boolean }) {
  const g = genome(handle, engine);
  const glyph = detail === "glyph";
  // A glyph is pulled further inside the circle; the simple version may let an
  // ear, cap or antenna reach just past it.
  const scale = glyph ? 0.8 : 0.92;
  return (
    <svg
      viewBox="0 0 100 100"
      aria-hidden
      data-family={g.family}
      data-detail={detail}
      className="block size-full overflow-visible"
    >
      <g transform={`translate(50 52) scale(${scale}) rotate(${g.tilt}) translate(-50 -52)`}>
        <Creature g={g} c={palette(tint)} glyph={glyph} />
      </g>
    </svg>
  );
}
