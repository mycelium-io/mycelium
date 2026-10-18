# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The app's themes on this machine: a folder of theme files, and the one in use.

A theme is a JSON file in ``~/.mycelium/themes/``, in the shape the app's paste
box takes: ``{"name", "mode", "colors"}``. Which one the app shows is
``~/.mycelium/theme.json``. Nothing here talks to a hub: the app's own server
on this machine reads the same folder and file and follows them as they change,
so writing a theme here (with ``mycelium theme`` or any editor) shows up in the
app at once.

What a theme may contain is ``contracts/custom-theme.json``; the app's parser
(``lib/custom-themes.ts``) reads the same rules and also checks contrast.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The colors a theme has to give, may give, and may give with alpha.
REQUIRED_COLORS = (
    "bg",
    "surface",
    "paper",
    "elevated",
    "muted-bg",
    "text",
    "muted-foreground",
    "faint",
    "accent",
    "accent-fg",
    "green",
    "yellow",
    "red",
)
OPTIONAL_COLORS = ("prose", "border", "border2", "hairline", "accent-soft", "avatar-ink")
TRANSLUCENT = frozenset({"border", "border2", "hairline", "accent-soft"})
NAME_MAX = 40
#: The themes the app ships, by id, label and mode.
BUILTIN: tuple[tuple[str, str, str], ...] = (
    ("light", "Mycelium light", "light"),
    ("dark", "Mycelium dark", "dark"),
    ("catppuccin-latte", "Catppuccin Latte", "light"),
    ("catppuccin-mocha", "Catppuccin Mocha", "dark"),
    ("dracula", "Dracula", "dark"),
    ("github-light", "GitHub light", "light"),
    ("github-dark", "GitHub dark", "dark"),
    ("gruvbox-light", "Gruvbox light", "light"),
    ("gruvbox-dark", "Gruvbox dark", "dark"),
    ("high-contrast-light", "High contrast light", "light"),
    ("high-contrast-dark", "High contrast dark", "dark"),
    ("nord", "Nord", "dark"),
    ("one-dark", "One Dark", "dark"),
    ("solarized-light", "Solarized light", "light"),
    ("solarized-dark", "Solarized dark", "dark"),
    ("tokyo-night", "Tokyo Night", "dark"),
)
#: Follow the computer's light or dark setting.
SYSTEM = "system"
CUSTOM_PREFIX = "custom-"
#: The most a downloaded theme may weigh; a theme is a few hundred bytes.
MAX_BYTES = 64 * 1024

_ALL = frozenset(REQUIRED_COLORS + OPTIONAL_COLORS)
_SOLID = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_ANY_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$", re.IGNORECASE)


class ThemeError(ValueError):
    """A theme that won't do, with every reason, or a name there's no theme for."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(" ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    mode: str
    colors: dict[str, str]

    def as_file(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "colors": self.colors}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _normalize(hex_color: str) -> str:
    h = hex_color.lower()
    return "#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h


def parse(raw: Any) -> Theme:
    """A theme from JSON text or a parsed value, or every reason it isn't one."""
    value = raw
    if isinstance(raw, str | bytes):
        try:
            value = json.loads(raw)
        except ValueError as err:
            msg = "That isn't JSON. A theme is an object with a name, a mode and its colors."
            raise ThemeError([msg]) from err
    if not isinstance(value, dict):
        raise ThemeError(["A theme is an object with a name, a mode and its colors."])
    errors: list[str] = []
    name = value.get("name")
    title = name.strip() if isinstance(name, str) else ""
    if not title:
        errors.append('It needs a "name".')
    elif len(title) > NAME_MAX:
        errors.append(f"Its name is longer than {NAME_MAX} characters.")
    elif not slug(title):
        errors.append("Its name needs at least one letter or digit.")
    mode = value.get("mode")
    if mode not in ("light", "dark"):
        errors.append('Its "mode" has to be "light" or "dark".')
    colors = value.get("colors")
    if not isinstance(colors, dict):
        errors.append('It needs "colors": an object of the app\'s color names to hex colors.')
        raise ThemeError(errors)
    out: dict[str, str] = {}
    for key, color in colors.items():
        if key not in _ALL:
            errors.append(f'"{key}" isn\'t a color the app reads.')
            continue
        pattern = _ANY_HEX if key in TRANSLUCENT else _SOLID
        if not isinstance(color, str) or not pattern.match(color):
            form = "#rgb, #rrggbb or #rrggbbaa" if key in TRANSLUCENT else "#rgb or #rrggbb"
            errors.append(f'"{key}" has to be a hex color ({form}).')
            continue
        out[key] = _normalize(color)
    missing = [c for c in REQUIRED_COLORS if c not in colors]
    if missing:
        errors.append("It's missing " + ", ".join(f'"{m}"' for m in missing) + ".")
    if errors:
        raise ThemeError(errors)
    return Theme(id=CUSTOM_PREFIX + slug(title), name=title, mode=str(mode), colors=out)


# ── this machine's folder ────────────────────────────────────────────────────


def home() -> Path:
    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir()


def folder() -> Path:
    """Where this machine's themes are: ``~/.mycelium/themes/``."""
    return home() / "themes"


def pick_file() -> Path:
    """Which theme the app shows: ``~/.mycelium/theme.json``."""
    return home() / "theme.json"


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def custom_themes() -> list[Theme]:
    """The folder's themes, by name. A file that isn't one is left out."""
    base = folder()
    if not base.is_dir():
        return []
    found: dict[str, Theme] = {}
    for path in sorted(base.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            theme = parse(path.read_text(encoding="utf-8"))
        except (OSError, ThemeError):
            continue
        found.setdefault(theme.id, theme)
    return sorted(found.values(), key=lambda t: t.name.lower())


def save(raw: Any) -> tuple[Theme, Path]:
    """Add a theme to the folder, or replace the one with its name."""
    theme = parse(raw)
    path = folder() / f"{theme.id.removeprefix(CUSTOM_PREFIX)}.json"
    _atomic_write(path, theme.as_file())
    return theme, path


def find(name: str) -> Theme | None:
    """One of the folder's themes by its id (``custom-fern``), slug or name, any case."""
    want = name.strip().lower()
    for theme in custom_themes():
        if want in (theme.id, theme.id.removeprefix(CUSTOM_PREFIX), theme.name.lower()):
            return theme
    return None


def remove(name: str) -> Theme:
    """Delete one of the folder's themes, by its id or name."""
    theme = find(name)
    if theme is None:
        raise ThemeError([f"There's no theme of yours called {name!r}."])
    for path in folder().glob("*.json"):
        try:
            if parse(path.read_text(encoding="utf-8")).id == theme.id:
                path.unlink()
        except (OSError, ThemeError):
            continue
    return theme


def resolve(name: str) -> str:
    """The id ``name`` picks: ``system``, a built-in id or label, or one of the folder's."""
    want = name.strip().lower()
    if want == SYSTEM:
        return SYSTEM
    for theme_id, label, _mode in BUILTIN:
        if want in (theme_id, label.lower()):
            return theme_id
    custom = find(name)
    if custom is not None:
        return custom.id
    raise ThemeError([f"There's no theme called {name!r}. `mycelium theme ls` lists them."])


def current() -> str | None:
    """The theme the app shows, by id, or ``None`` when nothing's been picked here."""
    try:
        data = json.loads(pick_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    theme = data.get("theme") if isinstance(data, dict) else None
    return theme if isinstance(theme, str) and theme else None


def use(name: str) -> str:
    """Make ``name`` the theme the app shows; returns its id."""
    theme_id = resolve(name)
    _atomic_write(pick_file(), {"theme": theme_id})
    return theme_id


def download(url: str) -> bytes:
    """A theme file from ``url``: http(s) only, and small, as a theme is."""
    import httpx

    if not url.lower().startswith(("https://", "http://")):
        raise ThemeError([f"{url!r} isn't an http(s) address."])
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=15) as resp:
            if resp.status_code >= 400:
                raise ThemeError([f"Couldn't fetch {url}: HTTP {resp.status_code}."])
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ThemeError([f"{url} is bigger than a theme ({MAX_BYTES // 1024} KB)."])
    except httpx.HTTPError as err:
        raise ThemeError([f"Couldn't fetch {url}: {err}"]) from err
    return body
