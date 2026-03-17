"""
Spinning 3D hexagonal prism rendered as ASCII shader art.

Adapted from hexaart/hexspin.py for use as an embedded animation
in the HiveMind CLI. Call run_animation() to play for a fixed duration.
"""

import math
import os
import random
import sys
import threading
import time
from collections.abc import Callable

import numpy as np
import pyfiglet

# ── CONFIG ──────────────────────────────────────────────────────

HEX_RADIUS = 1.8
INNER_HEX_RADIUS = 1.2
TUBE_RADIUS = 0.12
CAMERA_DIST = 5.0

BODY_SAMPLES = 50
TUBE_LENGTH_SAMPLES = 80
TUBE_RING_SAMPLES = 30

ROTATION_SPEED_X = 0.008
ROTATION_SPEED_Y = 0.05
FRAME_DELAY = 0.03

BUMP_STRENGTH = 0.25
BUMP_FREQUENCY = 12.0
NOISE_AMOUNT = 0.03

NUM_SHADES = 70


# ── SHADE RAMPS ─────────────────────────────────────────────────

_ASCII_CHARS = " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"

ASCII_RAMP = list(_ASCII_CHARS)

# Themes: tuple of 2+ RGB stops, interpolated across the luminance range.
COLOR_THEMES: dict[str, tuple[tuple[int, int, int], ...]] = {
    "cyan": (
        (2, 10, 20),       # deep ocean
        (5, 30, 60),       # midnight teal
        (10, 60, 100),     # dark sea
        (15, 95, 130),     # teal shadow
        (25, 140, 160),    # ocean teal
        (50, 190, 190),    # bright teal
        (70, 220, 210),    # aqua
        (100, 245, 230),   # electric cyan
        (170, 255, 245),   # pale mint
        (240, 255, 255),   # ice white
    ),
    "amber": ((50, 25, 0), (255, 200, 50)),
    "magenta": ((40, 5, 50), (255, 80, 220)),
    "green": ((5, 35, 10), (50, 255, 120)),
    "white": ((30, 30, 30), (255, 255, 255)),
    "purple": (
        (3, 1, 10),        # void
        (25, 5, 60),       # midnight purple
        (60, 15, 130),     # deep violet
        (100, 30, 190),    # royal purple
        (120, 50, 230),    # vivid purple
        (90, 90, 250),     # purple-blue bridge
        (60, 140, 255),    # electric blue
        (140, 200, 255),   # sky blue
        (210, 230, 255),   # pale ice
        (255, 255, 255),   # pure white
    ),
}


def _sample_theme(theme: str, t: float) -> tuple[int, int, int]:
    """Interpolate a color at position *t* (0..1) across a multi-stop theme."""
    stops = COLOR_THEMES.get(theme, COLOR_THEMES["cyan"])
    if len(stops) == 2:
        a, b = stops
        return (
            int(a[0] + t * (b[0] - a[0])),
            int(a[1] + t * (b[1] - a[1])),
            int(a[2] + t * (b[2] - a[2])),
        )
    # Multi-stop: find the segment
    n_seg = len(stops) - 1
    pos = t * n_seg
    idx = min(int(pos), n_seg - 1)
    frac = pos - idx
    a, b = stops[idx], stops[idx + 1]
    return (
        int(a[0] + frac * (b[0] - a[0])),
        int(a[1] + frac * (b[1] - a[1])),
        int(a[2] + frac * (b[2] - a[2])),
    )


def _build_unicode_ramp(n: int = NUM_SHADES) -> list[str]:
    ramp: list[str] = [" "]
    for i in range(1, n):
        t = i / (n - 1)
        gray = int(t * 255)
        if t < 0.25:
            ch = "\u2591"
        elif t < 0.50:
            ch = "\u2592"
        elif t < 0.75:
            ch = "\u2593"
        else:
            ch = "\u2588"
        ramp.append(f"\x1b[38;2;{gray};{gray};{gray}m{ch}")
    return ramp


def _build_braille_ramp(n: int = NUM_SHADES, theme: str = "cyan") -> list[str]:
    """Braille dot density for texture, ANSI 24-bit color for lighting."""
    # 16 braille chars ordered by ascending dot density (0→8 dots, with intermediates)
    _BRAILLE = " \u2801\u2802\u2803\u2809\u280b\u2819\u281b\u281f\u282f\u2837\u283f\u28bf\u28ef\u28ff\u28ff"
    ramp: list[str] = [" "]
    for i in range(1, n):
        t = i / (n - 1)
        # Lift floor to 50% so braille dots are visible on dark terminals
        lifted_t = 0.5 + t * 0.5
        r, gn, b = _sample_theme(theme, lifted_t)
        ch = _BRAILLE[int(t * (len(_BRAILLE) - 1))]
        ramp.append(f"\x1b[38;2;{r};{gn};{b}m{ch}")
    return ramp


def _build_colored_ascii_ramp(n: int = NUM_SHADES, theme: str = "cyan") -> list[str]:
    """ASCII density characters with multi-stop theme gradient."""
    chars = _ASCII_CHARS
    ramp: list[str] = [" "]
    for i in range(1, n):
        t = i / (n - 1)
        # Lift floor to 30% so dimmest chars are visible on dark terminals
        lifted_t = 0.3 + t * 0.7
        r, gn, b = _sample_theme(theme, lifted_t)
        ch = chars[int(t * (len(chars) - 1))]
        ramp.append(f"\x1b[38;2;{r};{gn};{b}m{ch}")
    return ramp


# ── BRAILLE RAIN ───────────────────────────────────────────────

_RAIN_DROPS = [
    "\u2802",  # ⠂  single dot
    "\u2803",  # ⠃  2-dot streak
    "\u2807",  # ⠇  3-dot streak
    "\u2847",  # ⡇  4-dot streak
]


class _RainState:
    """Persistent state for braille raindrop effect."""

    def __init__(self, width: int, height: int, density: float = 0.006):
        self.width = width
        self.height = height
        self.density = density
        self.drops: list[list[float]] = []

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def update(self) -> None:
        self.drops = [
            [x, y + spd, spd, brt]
            for x, y, spd, brt in self.drops
            if y + spd < self.height
        ]
        num_new = max(1, int(self.width * self.density))
        for _ in range(num_new):
            self.drops.append([
                random.randint(0, self.width - 1),
                -random.uniform(0, 2),
                random.uniform(0.15, 0.45),
                random.uniform(0.1, 0.4),
            ])

    def overlay(
        self, screen_w: int, screen_h: int, theme: str,
    ) -> tuple[list[bool], list[str]]:
        """Build flat mask + char arrays for rain compositing."""
        size = screen_w * screen_h
        mask = [False] * size
        chars = [""] * size
        for x, y, spd, brt in self.drops:
            r_idx, c_idx = int(y), int(x)
            if 0 <= r_idx < screen_h and 0 <= c_idx < screen_w:
                idx = r_idx * screen_w + c_idx
                if not mask[idx]:
                    r, g, b = _sample_theme(theme, brt)
                    si = min(int(spd / 0.3), len(_RAIN_DROPS) - 1)
                    mask[idx] = True
                    chars[idx] = f"\x1b[38;2;{r};{g};{b}m{_RAIN_DROPS[si]}"
        return mask, chars


# ── TEXT BANNER ─────────────────────────────────────────────────


def _render_banner(
    text: str, screen_w: int, is_unicode: bool = True, theme: str = "cyan",
) -> list[str]:
    raw = pyfiglet.figlet_format(text, font="slant")
    raw_lines = raw.rstrip("\n").split("\n")
    max_len = max(len(line) for line in raw_lines)

    result: list[str] = []
    for line in raw_lines:
        pad = max(0, (screen_w - max_len) // 2)

        if not is_unicode:
            result.append("\x1b[0m" + " " * pad + line)
            continue

        parts = [" " * pad]
        for ci, ch in enumerate(line):
            if ch == " ":
                parts.append(" ")
            else:
                # Horizontal gradient: 60%..100% of the theme range
                t = 0.6 + 0.4 * (ci / max(max_len - 1, 1))
                r, g, b = _sample_theme(theme, t)
                parts.append(f"\x1b[38;2;{r};{g};{b}m{ch}")
        parts.append("\x1b[0m")
        result.append("".join(parts))
    return result


# ── HEXAGON GEOMETRY ────────────────────────────────────────────


def _build_hex_geometry(
    radius: float = HEX_RADIUS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    angles = np.arange(6) * (math.pi / 3)
    vertices_x = radius * np.cos(angles)
    vertices_y = radius * np.sin(angles)
    normal_angles = angles + math.pi / 6
    normals_x = np.cos(normal_angles)
    normals_y = np.sin(normal_angles)
    return vertices_x, vertices_y, normals_x, normals_y


# ── 3D ROTATION ─────────────────────────────────────────────────


def _rotate_points(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    cos_a: float,
    sin_a: float,
    cos_b: float,
    sin_b: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ry = py * cos_a - pz * sin_a
    rz = py * sin_a + pz * cos_a
    rx = px * cos_b + rz * sin_b
    rz2 = -px * sin_b + rz * cos_b
    return rx, ry, rz2


# ── PROJECTION + SHADING ───────────────────────────────────────


def _perturb_normals(
    rnx: np.ndarray,
    rny: np.ndarray,
    rnz: np.ndarray,
    orig_px: np.ndarray,
    orig_py: np.ndarray,
    orig_pz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = BUMP_FREQUENCY
    s = BUMP_STRENGTH
    bump_x = s * np.sin(f * orig_py) * np.cos(f * orig_pz * 1.3)
    bump_y = s * np.cos(f * orig_px * 1.1) * np.sin(f * orig_pz * 0.9)
    bump_z = s * np.sin(f * orig_px * 0.8 + f * orig_py * 0.7)
    pnx = rnx + bump_x
    pny = rny + bump_y
    pnz = rnz + bump_z
    length = np.sqrt(pnx**2 + pny**2 + pnz**2)
    length = np.maximum(length, 1e-6)
    return pnx / length, pny / length, pnz / length


def _project_and_shade(
    rx: np.ndarray,
    ry: np.ndarray,
    rz: np.ndarray,
    rnx: np.ndarray,
    rny: np.ndarray,
    rnz: np.ndarray,
    screen_w: int,
    screen_h: int,
    kx: float,
    ky: float,
    z_buf: np.ndarray,
    shade_buf: np.ndarray,
    orig_px: np.ndarray,
    orig_py: np.ndarray,
    orig_pz: np.ndarray,
    y_offset: float = 0.0,
) -> None:
    ooz = 1.0 / (rz + CAMERA_DIST)
    sx = (screen_w * 0.5 + kx * rx * ooz).astype(int)
    sy = (screen_h * 0.42 - ky * ry * ooz + y_offset).astype(int)
    camera_facing = rnz > -0.1
    pnx, pny, pnz = _perturb_normals(rnx, rny, rnz, orig_px, orig_py, orig_pz)
    luminance = 0.6 * pnz + 0.4 * pny + 0.2 * pnx
    luminance += np.random.uniform(-NOISE_AMOUNT, NOISE_AMOUNT, luminance.shape)
    luminance = np.clip(luminance, 0.0, 1.0) * 0.85 + 0.15
    shade_idx = np.clip((luminance * (NUM_SHADES - 1)).astype(int), 1, NUM_SHADES - 1)
    on_screen = (sx >= 0) & (sx < screen_w) & (sy >= 0) & (sy < screen_h) & camera_facing
    flat_idx = sy * screen_w + sx
    for i in np.where(on_screen.ravel())[0]:
        fi = flat_idx.ravel()[i]
        z = ooz.ravel()[i]
        if z > z_buf[fi]:
            z_buf[fi] = z
            shade_buf[fi] = shade_idx.ravel()[i]


# ── SURFACE SAMPLING ────────────────────────────────────────────


def _sample_hex_tubes(
    vx: np.ndarray, vy: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    t_vals = np.linspace(0, 1, TUBE_LENGTH_SAMPLES)
    theta_vals = np.linspace(0, 2 * math.pi, TUBE_RING_SAMPLES, endpoint=False)
    tt, th = np.meshgrid(t_vals, theta_vals)

    all_px, all_py, all_pz = [], [], []
    all_nx, all_ny, all_nz = [], [], []

    for i in range(6):
        j = (i + 1) % 6
        dx = vx[j] - vx[i]
        dy = vy[j] - vy[i]
        edge_len = math.sqrt(dx**2 + dy**2)
        ux, uy = -dy / edge_len, dx / edge_len

        cx = vx[i] + tt * dx
        cy = vy[i] + tt * dy
        cz = np.zeros_like(tt)

        cos_th = np.cos(th)
        sin_th = np.sin(th)
        r = TUBE_RADIUS

        px = cx + r * (cos_th * ux)
        py = cy + r * (cos_th * uy)
        pz = cz + r * sin_th

        nx = cos_th * ux
        ny = cos_th * uy
        nz = sin_th

        all_px.append(px.ravel())
        all_py.append(py.ravel())
        all_pz.append(pz.ravel())
        all_nx.append(nx.ravel())
        all_ny.append(ny.ravel())
        all_nz.append(nz.ravel())

    return (
        np.concatenate(all_px),
        np.concatenate(all_py),
        np.concatenate(all_pz),
        np.concatenate(all_nx),
        np.concatenate(all_ny),
        np.concatenate(all_nz),
    )


def _sample_hex_body(
    vx: np.ndarray, vy: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    s = np.linspace(0, 1, BODY_SAMPLES)
    ss1, ss2 = np.meshgrid(s, s)
    mask = (ss1 + ss2) <= 1.0
    ss1 = ss1[mask]
    ss2 = ss2[mask]

    shrink = (HEX_RADIUS - TUBE_RADIUS * 2) / HEX_RADIUS
    ivx = vx * shrink
    ivy = vy * shrink

    all_px, all_py, all_pz = [], [], []
    all_nx, all_ny, all_nz = [], [], []

    for face_sign in [-1.0, 1.0]:
        for i in range(6):
            j = (i + 1) % 6
            px = ss1 * ivx[i] + ss2 * ivx[j]
            py = ss1 * ivy[i] + ss2 * ivy[j]
            pz = np.zeros_like(px)
            all_px.append(px)
            all_py.append(py)
            all_pz.append(pz)
            all_nx.append(np.zeros_like(px))
            all_ny.append(np.zeros_like(px))
            all_nz.append(np.full_like(px, face_sign))

    return (
        np.concatenate(all_px),
        np.concatenate(all_py),
        np.concatenate(all_pz),
        np.concatenate(all_nx),
        np.concatenate(all_ny),
        np.concatenate(all_nz),
    )


# ── RENDER ONE FRAME ────────────────────────────────────────────


def _get_term_size() -> tuple[int, int]:
    try:
        ts = os.get_terminal_size()
        return min(ts.columns, 160), min(ts.lines - 1, 60)
    except OSError:
        return 80, 24


def _render_frame(
    angle_x: float,
    angle_y: float,
    screen_w: int,
    screen_h: int,
    kx: float,
    ky: float,
    tube_geom: tuple[np.ndarray, ...],
    shade_ramp: list[str],
    theme: str = "cyan",
    body_geom: tuple[np.ndarray, ...] | None = None,
    body_opacity: float = 0.0,
    color_banner: bool = True,
    rain_mask: list[bool] | None = None,
    rain_chars: list[str] | None = None,
    inner_tube_geom: tuple[np.ndarray, ...] | None = None,
    inner_shade_ramp: list[str] | None = None,
    y_offset: float = 0.0,
) -> str:
    buf_size = screen_w * screen_h
    z_buf = np.zeros(buf_size)
    shade_buf = np.zeros(buf_size, dtype=int)
    source_buf = np.zeros(buf_size, dtype=int)  # 0=outer, 1=inner

    ca, sa = math.cos(angle_x), math.sin(angle_x)
    cb, sb = math.cos(angle_y), math.sin(angle_y)

    if body_geom is not None and body_opacity > 0:
        bpx, bpy, bpz, bnx, bny, bnz = body_geom
        rx, ry, rz = _rotate_points(bpx, bpy, bpz, ca, sa, cb, sb)
        rnx, rny, rnz = _rotate_points(bnx, bny, bnz, ca, sa, cb, sb)
        _project_and_shade(
            rx, ry, rz, rnx, rny, rnz, screen_w, screen_h, kx, ky, z_buf, shade_buf,
            bpx, bpy, bpz, y_offset=y_offset,
        )
        if body_opacity < 1.0:
            body_mask = shade_buf > 0
            scaled = (shade_buf[body_mask] * body_opacity).astype(int)
            shade_buf[body_mask] = scaled

    px, py, pz, nx_o, ny_o, nz_o = tube_geom
    rx, ry, rz = _rotate_points(px, py, pz, ca, sa, cb, sb)
    rnx, rny, rnz = _rotate_points(nx_o, ny_o, nz_o, ca, sa, cb, sb)
    _project_and_shade(
        rx, ry, rz, rnx, rny, rnz, screen_w, screen_h, kx, ky, z_buf, shade_buf,
        px, py, pz, y_offset=y_offset,
    )

    if inner_tube_geom is not None:
        # Snapshot z_buf before inner hex so we can detect which pixels it won
        z_before = z_buf.copy()
        ipx, ipy, ipz, inx, iny, inz = inner_tube_geom
        irx, iry, irz = _rotate_points(ipx, ipy, ipz, ca, sa, cb, sb)
        irnx, irny, irnz = _rotate_points(inx, iny, inz, ca, sa, cb, sb)
        _project_and_shade(
            irx, iry, irz, irnx, irny, irnz, screen_w, screen_h, kx, ky,
            z_buf, shade_buf, ipx, ipy, ipz, y_offset=y_offset,
        )
        # Mark pixels where inner hex is in front
        source_buf[z_buf > z_before] = 1

    ramps = [shade_ramp, inner_shade_ramp or shade_ramp]

    lines = []
    for row in range(screen_h):
        start = row * screen_w
        if rain_mask is not None:
            cells = []
            for col in range(screen_w):
                idx = start + col
                if shade_buf[idx] > 0:
                    cells.append(ramps[source_buf[idx]][shade_buf[idx]])
                elif rain_mask[idx]:
                    cells.append(rain_chars[idx])
                else:
                    cells.append(" ")
        else:
            cells = [
                ramps[source_buf[start + col]][shade_buf[start + col]]
                for col in range(screen_w)
            ]
        lines.append("".join(cells))

    has_ansi = len(shade_ramp[1]) > 1
    if has_ansi:
        lines[-1] += "\x1b[0m"

    banner = _render_banner("mycelium", screen_w, is_unicode=color_banner, theme=theme)
    banner_h = len(banner) + 1
    if screen_h > banner_h + 5:
        for i in range(banner_h):
            row = screen_h - banner_h + i
            if i == 0:
                lines[row] = ""
            else:
                lines[row] = banner[i - 1]

    return "\n".join(lines)


# ── PUBLIC API ──────────────────────────────────────────────────


def run_animation_with_output(
    output_timeline: list[tuple[float, list[str]]],
    height: int = 20,
    theme: str = "cyan",
    fill: float = 0.0,
    mode: str = "ascii",
    linger: float = 1.0,
    rain: bool = False,
    skip_intro: bool = False,
    wipe: bool = False,
) -> None:
    """
    Play the hex animation with timed output lines appearing below it.

    Each frame redraws the entire region (animation + output) in a single
    write — no threads, no cursor save/restore, no scrollback pollution.

    Parameters
    ----------
    output_timeline : list of (time, lines)
        Sorted list of ``(seconds_offset, lines_to_display)`` snapshots.
        Each snapshot replaces the previous output block.
    height : int
        Number of terminal lines for the animation area (default 20).
    theme : str
        Color theme.
    fill : float
        Body opacity.
    mode : str
        Rendering mode — 'ascii', 'braille', or 'blocks'.
    linger : float
        Extra seconds to animate after the last timeline entry.
    skip_intro : bool
        If True, skip the drop-in intro animation (hex appears immediately).
    """
    inner_theme = "purple" if theme != "purple" else "cyan"

    if mode == "blocks":
        shade_ramp = _build_unicode_ramp(NUM_SHADES)
        inner_shade_ramp = shade_ramp  # blocks mode has no color
    elif mode == "braille":
        shade_ramp = _build_braille_ramp(NUM_SHADES, theme=theme)
        inner_shade_ramp = _build_braille_ramp(NUM_SHADES, theme=inner_theme)
    else:
        shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=theme)
        inner_shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=inner_theme)

    vx, vy, _, _ = _build_hex_geometry()
    tube_geom = _sample_hex_tubes(vx, vy)
    body_geom = _sample_hex_body(vx, vy) if fill > 0 else None

    # Inner hexagon: smaller, same orientation, nested inside the outer one
    ivx, ivy, _, _ = _build_hex_geometry(radius=INNER_HEX_RADIUS)
    inner_tube_geom = _sample_hex_tubes(ivx, ivy)

    screen_w = _get_term_size()[0]
    screen_h = height
    # Auto-fit: derive projection scales from the HEIGHT so the hex never clips.
    # max_ooz is the worst-case perspective factor (nearest point to camera).
    max_ooz = 1.0 / (CAMERA_DIST - HEX_RADIUS)
    # Hex centre sits at 42% from the top (see _project_and_shade), so the
    # tightest vertical budget is min(0.42, 0.58) * screen_h ≈ 0.38 * screen_h.
    ky = (screen_h * 0.35) / (HEX_RADIUS * max_ooz)
    # 2x for terminal character aspect ratio (~2:1 height:width)
    kx = ky * 2.0

    # Work out the maximum number of output lines across all snapshots
    max_output = max((len(snap) for _, snap in output_timeline), default=0)
    total_h = height + max_output

    # Reserve the full region so the terminal never scrolls mid-animation
    sys.stdout.write("\n" * total_h)
    sys.stdout.write(f"\x1b[{total_h}A")
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    # Drop-in intro: hex falls from above over INTRO_DURATION seconds
    INTRO_DURATION = 0.0 if skip_intro else 1.0

    # Shift timeline so install text starts after intro
    if INTRO_DURATION > 0:
        output_timeline = [(t + INTRO_DURATION, lines) for t, lines in output_timeline]

    final_time = (output_timeline[-1][0] if output_timeline else 0.0) + linger
    timeline_idx = 0
    current_output: list[str] = []

    angle_x, angle_y = 0.55, 0.0  # fixed tilt so the hex always shows depth
    rain_state = _RainState(screen_w, screen_h) if rain else None
    first_frame = True
    start_time = time.monotonic()
    _interrupted = False

    try:
        while time.monotonic() - start_time < final_time:
            elapsed = time.monotonic() - start_time

            # Drop-in: slide hex from above the viewport to center
            if elapsed < INTRO_DURATION:
                t_intro = elapsed / INTRO_DURATION
                ease = 1.0 - (1.0 - t_intro) ** 3  # ease-out cubic
                y_offset = -screen_h * (1.0 - ease)
            else:
                y_offset = 0.0

            # Advance the output timeline
            while (
                timeline_idx < len(output_timeline)
                and output_timeline[timeline_idx][0] <= elapsed
            ):
                current_output = output_timeline[timeline_idx][1]
                timeline_idx += 1

            screen_w = _get_term_size()[0]

            rain_mask_buf = None
            rain_char_buf = None
            if rain_state is not None:
                rain_state.resize(screen_w, screen_h)
                rain_state.update()
                rain_mask_buf, rain_char_buf = rain_state.overlay(
                    screen_w, screen_h, theme,
                )

            frame = _render_frame(
                angle_x, angle_y, screen_w, screen_h, kx, ky,
                tube_geom, shade_ramp, theme=theme, body_geom=body_geom,
                body_opacity=fill, color_banner=True,
                rain_mask=rain_mask_buf, rain_chars=rain_char_buf,
                inner_tube_geom=inner_tube_geom,
                inner_shade_ramp=inner_shade_ramp,
                y_offset=y_offset,
            )

            # Build the full region: animation lines + output lines, padded
            frame_lines = frame.split("\n")
            # Reset color before each output line so hex ANSI state doesn't bleed
            reset_output = ["\x1b[0m" + ln for ln in current_output]
            all_lines = frame_lines + reset_output
            while len(all_lines) < total_h:
                all_lines.append("")

            # Move cursor to the top of the region (except first frame)
            if not first_frame:
                sys.stdout.write(f"\x1b[{total_h}A")
            first_frame = False

            # Write every line, clearing trailing chars from previous frames
            buf = "".join(f"\r{line}\x1b[K\n" for line in all_lines)
            sys.stdout.write(buf)
            sys.stdout.flush()

            angle_y += ROTATION_SPEED_Y
            time.sleep(FRAME_DELAY)
    except KeyboardInterrupt:
        _interrupted = True
    finally:
        trailing_blanks = max_output - len(current_output)
        if trailing_blanks > 0:
            sys.stdout.write(f"\x1b[{trailing_blanks}A")
        if wipe:
            # Settle on a clean face-on frame, then clear output lines below it.
            # Go back to the top of the hex area.
            lines_to_top = height + len(current_output)
            sys.stdout.write(f"\x1b[{lines_to_top}A")
            # Render one frame at the "face toward viewer" orientation — no rain.
            face_frame = _render_frame(
                0.55, 0.0, screen_w, height, kx, ky,
                tube_geom, shade_ramp, theme=theme,
                body_geom=body_geom, body_opacity=fill,
                color_banner=True,
                rain_mask=None, rain_chars=None,
                inner_tube_geom=inner_tube_geom,
                inner_shade_ramp=inner_shade_ramp,
            )
            sys.stdout.write("".join(f"\r{line}\x1b[K\n" for line in face_frame.split("\n")))
            # Clear everything below the hex (output lines) and leave cursor there.
            sys.stdout.write("\x1b[J")
            sys.stdout.write("\x1b[0m\x1b[?25h")
        else:
            sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()
    if _interrupted:
        raise KeyboardInterrupt


def run_animation_live(
    get_lines: Callable[[], list[str]],
    done: threading.Event,
    height: int = 20,
    theme: str = "cyan",
    fill: float = 0.0,
    mode: str = "ascii",
    rain: bool = False,
    wipe: bool = False,
    linger: float = 0.5,
) -> None:
    """
    Play the hex animation until *done* is set, calling *get_lines()* each
    frame to get the current output lines to show below the hex.

    Useful for showing real-time progress of background work (e.g. image pulls).
    """
    inner_theme = "purple" if theme != "purple" else "cyan"

    if mode == "blocks":
        shade_ramp = _build_unicode_ramp(NUM_SHADES)
        inner_shade_ramp = shade_ramp
    elif mode == "braille":
        shade_ramp = _build_braille_ramp(NUM_SHADES, theme=theme)
        inner_shade_ramp = _build_braille_ramp(NUM_SHADES, theme=inner_theme)
    else:
        shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=theme)
        inner_shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=inner_theme)

    vx, vy, _, _ = _build_hex_geometry()
    tube_geom = _sample_hex_tubes(vx, vy)
    body_geom = _sample_hex_body(vx, vy) if fill > 0 else None
    ivx, ivy, _, _ = _build_hex_geometry(radius=INNER_HEX_RADIUS)
    inner_tube_geom = _sample_hex_tubes(ivx, ivy)

    screen_w = _get_term_size()[0]
    max_ooz = 1.0 / (CAMERA_DIST - HEX_RADIUS)
    ky = (height * 0.35) / (HEX_RADIUS * max_ooz)
    kx = ky * 2.0

    rain_state = _RainState(screen_w, height) if rain else None
    angle_x, angle_y = 0.55, 0.0
    prev_total = 0
    first_frame = True
    current_output: list[str] = []
    _interrupted = False

    # Reserve space
    sys.stdout.write("\n" * height)
    sys.stdout.write(f"\x1b[{height}A")
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    linger_until: float | None = None

    try:
        while True:
            if done.is_set():
                if linger_until is None:
                    linger_until = time.monotonic() + linger
                elif time.monotonic() >= linger_until:
                    break

            screen_w = _get_term_size()[0]
            current_output = get_lines()

            rain_mask_buf = rain_char_buf = None
            if rain_state is not None:
                rain_state.resize(screen_w, height)
                rain_state.update()
                rain_mask_buf, rain_char_buf = rain_state.overlay(screen_w, height, theme)

            frame = _render_frame(
                angle_x, angle_y, screen_w, height, kx, ky,
                tube_geom, shade_ramp, theme=theme,
                body_geom=body_geom, body_opacity=fill,
                color_banner=True,
                rain_mask=rain_mask_buf, rain_chars=rain_char_buf,
                inner_tube_geom=inner_tube_geom,
                inner_shade_ramp=inner_shade_ramp,
            )

            total = height + len(current_output)
            if not first_frame:
                sys.stdout.write(f"\x1b[{prev_total}A")
            first_frame = False

            frame_lines = frame.split("\n")
            buf = "".join(f"\r{line}\x1b[K\n" for line in frame_lines)
            buf += "".join(f"\r\x1b[0m{line}\x1b[K\n" for line in current_output)
            sys.stdout.write(buf)
            sys.stdout.flush()
            prev_total = total

            angle_y += ROTATION_SPEED_Y
            time.sleep(FRAME_DELAY)

    except KeyboardInterrupt:
        _interrupted = True
    finally:
        if wipe:
            lines_to_top = height + len(current_output)
            sys.stdout.write(f"\x1b[{lines_to_top}A")
            face_frame = _render_frame(
                0.55, 0.0, screen_w, height, kx, ky,
                tube_geom, shade_ramp, theme=theme,
                body_geom=body_geom, body_opacity=fill,
                color_banner=True,
                rain_mask=None, rain_chars=None,
                inner_tube_geom=inner_tube_geom,
                inner_shade_ramp=inner_shade_ramp,
            )
            sys.stdout.write("".join(f"\r{line}\x1b[K\n" for line in face_frame.split("\n")))
            sys.stdout.write("\x1b[J")
            sys.stdout.write("\x1b[0m\x1b[?25h")
        else:
            sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()

    if _interrupted:
        raise KeyboardInterrupt


class BackgroundAnimation:
    """
    Hex animation running in a daemon thread.

    The animation owns the top ``height`` terminal lines plus the output
    lines below them.  ``prompt()`` appends an input line, reads a reply,
    and undoes the trailing newline so cursor position stays consistent.

    Usage::

        with BackgroundAnimation(height=16, theme="cyan") as anim:
            anim.set_output(["  ? Question", "    1) option"])
            answer = anim.prompt("  Choice [1]: ", default="1")
    """

    def __init__(
        self,
        height: int = 16,
        theme: str = "cyan",
        mode: str = "braille",
        fill: float = 0.15,
        rain: bool = True,
    ) -> None:
        self._height = height
        self._theme = theme
        self._mode = mode
        self._fill = fill
        self._rain = rain
        self._stop = threading.Event()
        # Lock is held by the animation thread during each terminal write.
        # prompt() acquires it to pause animation while showing the input line.
        self._lock = threading.Lock()
        self._output: list[str] = []
        self._prev_total: int = height   # total lines written last frame
        self._thread: threading.Thread | None = None
        self._interrupted = False

    # ── context manager ──────────────────────────────────────────

    def __enter__(self) -> "BackgroundAnimation":
        self._setup()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        sys.stdout.write("\x1b[0m\x1b[?25h")
        sys.stdout.flush()

    # ── public helpers ────────────────────────────────────────────

    def set_output(self, lines: list[str]) -> None:
        """Swap the output lines shown below the hex (GIL-safe)."""
        self._output = list(lines)

    def prompt(self, text: str, default: str = "") -> str:
        """
        Pause the animation, show an input prompt below the output block,
        read a reply, then resume.  The enter-newline is undone so cursor
        stays at the same row for the next frame.
        """
        with self._lock:
            sys.stdout.write(f"\r\x1b[0m{text}\x1b[K")
            sys.stdout.write("\x1b[?25h")
            sys.stdout.flush()
            try:
                raw = input("")
            except (EOFError, KeyboardInterrupt):
                self._interrupted = True
                raise KeyboardInterrupt
            # Undo the newline written by Enter so cursor stays at prompt row.
            sys.stdout.write("\x1b[1A\r\x1b[K")
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()
        stripped = raw.strip()
        if stripped.lower() in ("q", "quit", "exit") or stripped.startswith("\x1b"):
            self._interrupted = True
            raise KeyboardInterrupt
        return stripped or default

    def interrupted(self) -> bool:
        return self._interrupted

    # ── internals ────────────────────────────────────────────────

    def _setup(self) -> None:
        """Reserve the animation area and hide cursor."""
        sys.stdout.write("\n" * self._height)
        sys.stdout.write(f"\x1b[{self._height}A")
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()

    def _run(self) -> None:
        inner_theme = "purple" if self._theme != "purple" else "cyan"

        if self._mode == "blocks":
            shade_ramp = _build_unicode_ramp(NUM_SHADES)
            inner_shade_ramp = shade_ramp
        elif self._mode == "braille":
            shade_ramp = _build_braille_ramp(NUM_SHADES, theme=self._theme)
            inner_shade_ramp = _build_braille_ramp(NUM_SHADES, theme=inner_theme)
        else:
            shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=self._theme)
            inner_shade_ramp = _build_colored_ascii_ramp(NUM_SHADES, theme=inner_theme)

        vx, vy, _, _ = _build_hex_geometry()
        tube_geom = _sample_hex_tubes(vx, vy)
        body_geom = _sample_hex_body(vx, vy) if self._fill > 0 else None
        ivx, ivy, _, _ = _build_hex_geometry(radius=INNER_HEX_RADIUS)
        inner_tube_geom = _sample_hex_tubes(ivx, ivy)

        screen_w = _get_term_size()[0]
        max_ooz = 1.0 / (CAMERA_DIST - HEX_RADIUS)
        ky = (self._height * 0.35) / (HEX_RADIUS * max_ooz)
        kx = ky * 2.0

        rain_state = _RainState(screen_w, self._height) if self._rain else None

        angle_x, angle_y = 0.55, 0.0
        prev_total = self._height
        first_frame = True

        while not self._stop.is_set():
            screen_w = _get_term_size()[0]

            rain_mask_buf = rain_char_buf = None
            if rain_state is not None:
                rain_state.resize(screen_w, self._height)
                rain_state.update()
                rain_mask_buf, rain_char_buf = rain_state.overlay(screen_w, self._height, self._theme)

            frame = _render_frame(
                angle_x, angle_y, screen_w, self._height, kx, ky,
                tube_geom, shade_ramp, theme=self._theme,
                body_geom=body_geom, body_opacity=self._fill,
                color_banner=True,
                rain_mask=rain_mask_buf, rain_chars=rain_char_buf,
                inner_tube_geom=inner_tube_geom,
                inner_shade_ramp=inner_shade_ramp,
            )

            output = list(self._output)   # snapshot
            total = self._height + len(output)

            with self._lock:
                if not first_frame:
                    sys.stdout.write(f"\x1b[{prev_total}A")
                first_frame = False

                # Hex frame
                frame_lines = frame.split("\n")
                sys.stdout.write("".join(f"\r{line}\x1b[K\n" for line in frame_lines))

                # Output lines (prompt options, confirmations, etc.)
                for line in output:
                    sys.stdout.write(f"\r\x1b[0m{line}\x1b[K\n")

                sys.stdout.flush()
                prev_total = total

            angle_y += ROTATION_SPEED_Y
            time.sleep(FRAME_DELAY)
