# Mycelium — Design System

Brand source: `mycelium-frontend/src/app/globals.css`. Use these exact values. Do not invent.

## Palette (dark theme)

| Token       | Hex / rgba                  | Use                                        |
| ----------- | --------------------------- | ------------------------------------------ |
| `bg`        | `#0c0d10`                   | App background, scene background           |
| `surface`   | `#111216`                   | Panel surface                              |
| `paper`     | `#14161b`                   | Card / header strip                        |
| `border`    | `rgba(234,234,234,0.10)`    | Hairline dividers                          |
| `border2`   | `rgba(234,234,234,0.22)`    | Stronger dividers, focused borders         |
| `accent`    | `#5dd4e0`                   | Cyan — primary accent, inline `code`, links |
| `accent2`   | `#7dd3fc`                   | Cool blue — secondary accent               |
| `green`     | `#34d399`                   | Success / OK state                          |
| `purple`    | `#c084fc`                   | Agent / negotiation accent                  |
| `yellow`    | `#fbbf24`                   | Warnings, transient state                   |
| `text`      | `#eaeaea`                   | Primary text                                |
| `text2`     | `#a8a6a0`                   | Secondary text (warm gray)                  |
| `muted`     | `#b8b5ae`                   | Tertiary text, labels                       |
| `dim`       | `#46443e`                   | Fully-dimmed                                 |

## Typography

| Family               | Stack                                                              | Use                                  |
| -------------------- | ------------------------------------------------------------------ | ------------------------------------ |
| `IBM Plex Sans`      | `"IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif`   | Body, UI, default                    |
| `Cormorant Garamond` | `"Cormorant Garamond", Georgia, serif`                             | Brand wordmark, hero display only    |
| `Geist Mono`         | `"Geist Mono", "SF Mono", "JetBrains Mono", Menlo, monospace`      | Terminal, code, caps-mono labels     |

**Caps-mono treatment** (used for section labels in the UI):
- `font-family: Geist Mono`
- `font-weight: 600`
- `letter-spacing: 0.16em`
- `text-transform: uppercase`

## Motifs

- **Square dot** (`.square-dot` in the UI): 8px outline square, sometimes filled, used as a glyph next to nav items. Reuse as a transition motif and as the agent presence indicator.
- **Hairline borders** at `rgba(234,234,234,0.10)` — every panel boundary uses this. Replicate in mock UI scenes.
- **Sigil prefixes** in the breadcrumbs: `rm:` for room, `ss:` for session. These are visual identity markers — keep them in mock UI scenes.

## Avoid

- Bright pure white (`#fff`) — use `text` (`#eaeaea`) instead. The frontend never goes brighter than that.
- Drop shadows on cards. The UI is flat-with-hairlines, not Material-elevated.
- Saturated reds. Mycelium has no red in its palette — use `yellow` for warning, `purple` for novelty.
- Web-UI-scale opacity (text at 60% alpha). At video scale that disappears — bump to ≥85% for any prose, 100% for headlines.

## Frame

- 1920 x 1080, 30 fps target.
- Background: solid `bg` (`#0c0d10`). No gradient backgrounds — H.264 banding on dark fields.
- For depth: localized radial glows of `accent` at low alpha, never full-frame gradients.
