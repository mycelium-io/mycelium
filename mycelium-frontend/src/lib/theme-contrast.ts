// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Which of a theme's colors have to be readable on which, and the WCAG math
 * that says whether they are. One list, used by the test that holds every
 * built-in theme to it and by the check run when someone imports their own.
 */

/** WCAG AA for body text. */
export const AA = 4.5;

const SURFACES = ["bg", "surface", "paper", "elevated", "muted-bg"];

/** Foregrounds that carry words, and the surfaces each must read on. */
export const CONTRAST_PAIRS: readonly [string, readonly string[]][] = [
  ["text", SURFACES],
  ["prose", SURFACES],
  ["muted-foreground", SURFACES],
  ["faint", SURFACES],
  // Links, mentions and the accent's own labels.
  ["accent", ["bg", "surface", "paper", "elevated"]],
  // State in words: an error line, "merged", "waiting".
  ["red", ["bg", "surface", "elevated"]],
  ["green", ["bg", "surface", "elevated"]],
  ["yellow", ["bg", "surface", "elevated"]],
  // The Stream names each task's thread in its lane's color.
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n): [string, string[]] => [`lane-${n}`, ["bg"]]),
];

/** What each token is called where a person reads a contrast problem. */
const NAMES: Record<string, string> = {
  text: "text",
  prose: "message text",
  "muted-foreground": "secondary text",
  faint: "faint text",
  accent: "the accent",
  "accent-fg": "text on the accent",
  red: "red",
  green: "green",
  yellow: "yellow",
  bg: "the background",
  surface: "panels",
  paper: "cards",
  elevated: "menus and dialogs",
  "muted-bg": "quiet fills",
};

export function tokenName(token: string): string {
  return NAMES[token] ?? token;
}

/** `#rgb` or `#rrggbb` as `[r, g, b]`, 0-255. */
export function rgb(hex: string): number[] {
  const h = hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join("")}` : hex;
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast between two colors, each a hex string or `[r, g, b]`. */
export function contrast(a: string | number[], b: string | number[]): number {
  const [x, y] = [a, b].map((c) => luminance(typeof c === "string" ? rgb(c) : c));
  const [hi, lo] = [x, y].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}

export interface ContrastProblem {
  fg: string;
  bg: string;
  ratio: number;
}

/** Every pair in ``tokens`` under AA. A pair whose colors the theme doesn't
 *  set (a custom theme leaving the lanes to the defaults, say) is skipped. */
export function contrastProblems(tokens: Record<string, string>): ContrastProblem[] {
  const pairs: [string, string][] = [
    ...CONTRAST_PAIRS.flatMap(([fg, bgs]) => bgs.map((bg): [string, string] => [fg, bg])),
    ["accent-fg", "accent"],
  ];
  return pairs
    .filter(([fg, bg]) => tokens[fg] && tokens[bg])
    .map(([fg, bg]) => ({ fg, bg, ratio: contrast(tokens[fg], tokens[bg]) }))
    .filter(({ ratio }) => ratio < AA);
}

/** One problem as a person reads it: "faint text on panels: 3.1:1". */
export function describeProblem({ fg, bg, ratio }: ContrastProblem): string {
  return `${tokenName(fg)} on ${tokenName(bg)}: ${ratio.toFixed(1)}:1`;
}
