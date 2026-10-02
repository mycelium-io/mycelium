# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Experiences: ready-made rooms to explore, added to this Mac from a file.

An experience is ours, never a third party's, and the app knows each one by
name (:data:`CATALOG`). What the person adds is its content: for the Patterns
Explorer, a pattern pack, a folder of ``scenarios/<pattern>/scenario.yaml``,
given as a ``.zip`` or a folder. Adding one copies the scenarios into
``~/.mycelium/experiences/<id>/pack`` and points the hub at them
(``patterns.dir``), with ``patterns.personas_only`` on, so a pack that arrived
as a file can never start a worker. The hub reads it when it next starts.

A pack is data: only ``scenarios/`` is copied, and from a zip nothing that
would land outside the folder, no link, and nothing past a size cap is
unpacked. The hub parses what is there with its own checks when it loads it.
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

#: What a zip may unpack to, in total.
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
#: How many files a zip may hold.
MAX_FILES = 2000


@dataclass(frozen=True)
class Experience:
    id: str
    title: str
    description: str
    #: Where it opens, in the room UI.
    open: str
    #: What a scenario in it is called, for the count beside it.
    unit: str


#: Frozen in ``contracts/experiences.json``, which the hub's list
#: (``app/routes/hub.py``) also matches; this package can't read the repo at run
#: time, so this is a checked copy of it.
CATALOG: tuple[Experience, ...] = (
    Experience(
        id="patterns-explorer",
        title="Patterns Explorer",
        description="Watch a team of agents work through a business scenario, start to finish.",
        open="/patterns",
        unit="business scenario",
    ),
)


class ExperienceError(ValueError):
    """Why an experience could not be added or removed, said to the person."""


def experiences_dir() -> Path:
    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir() / "experiences"


def _known(experience_id: str) -> Experience:
    for experience in CATALOG:
        if experience.id == experience_id:
            return experience
    msg = f"There's no experience called {experience_id!r}."
    raise ExperienceError(msg)


def _pack_of(experience: Experience) -> Path:
    return experiences_dir() / experience.id / "pack"


def _scenarios(pack: Path) -> list[str]:
    return sorted(p.parent.name for p in (pack / "scenarios").glob("*/scenario.yaml"))


def view(config: Any) -> list[dict[str, Any]]:
    """Every experience, and whether it is added on this Mac, as the app shows them."""
    pointed = Path(config.patterns.dir).expanduser().resolve() if config.patterns.dir else None
    out: list[dict[str, Any]] = []
    for experience in CATALOG:
        pack = _pack_of(experience)
        names = _scenarios(pack) if pack.is_dir() else []
        out.append(
            {
                "id": experience.id,
                "title": experience.title,
                "description": experience.description,
                "open": experience.open,
                "unit": experience.unit,
                "added": bool(names),
                # Added, but the hub was pointed somewhere else since.
                "active": bool(names) and pointed == pack.resolve(),
                "scenarios": len(names),
            }
        )
    return out


def _pack_root(folder: Path) -> Path:
    """The folder holding ``scenarios/``: the one given, or the one folder inside
    it, which is how a downloaded repository unpacks."""
    if (folder / "scenarios").is_dir():
        return folder
    inner = [p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "__"))]
    if len(inner) == 1 and (inner[0] / "scenarios").is_dir():
        return inner[0]
    msg = "That isn't a pattern pack: there's no scenarios folder in it."
    raise ExperienceError(msg)


def _unzip(archive: Path, into: Path) -> None:
    """Unpack ``archive`` into ``into``, refusing anything that isn't plain files
    and folders inside it."""
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        msg = "That file isn't a zip that can be opened."
        raise ExperienceError(msg) from None
    with zf:
        members = zf.infolist()
        if len(members) > MAX_FILES:
            msg = f"That zip holds more than {MAX_FILES} files; a pattern pack is far smaller."
            raise ExperienceError(msg)
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            msg = "That zip unpacks to more than 50 MB; a pattern pack is far smaller."
            raise ExperienceError(msg)
        for m in members:
            name = PurePosixPath(m.filename)
            if name.is_absolute() or ".." in name.parts:
                msg = f"That zip has a file that would land outside its folder ({m.filename})."
                raise ExperienceError(msg)
            if stat.S_ISLNK(m.external_attr >> 16):
                msg = f"That zip has a link in it ({m.filename}); a pattern pack has none."
                raise ExperienceError(msg)
        zf.extractall(into)


def add(config: Any, experience_id: str, source: Path) -> dict[str, Any]:
    """Add an experience's content from ``source`` (a ``.zip`` or a folder) and
    point the hub at it. ``config`` is changed; the caller saves it."""
    experience = _known(experience_id)
    source = source.expanduser()
    if not source.exists():
        msg = f"There's nothing at {source}."
        raise ExperienceError(msg)
    target = _pack_of(experience)
    with tempfile.TemporaryDirectory() as tmp:
        if source.is_dir():
            root = _pack_root(source)
        else:
            _unzip(source, Path(tmp))
            root = _pack_root(Path(tmp))
        names = _scenarios(root)
        if not names:
            msg = "That pack has a scenarios folder but no scenarios/<name>/scenario.yaml in it."
            raise ExperienceError(msg)
        staged = target.with_name("pack.new")
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        # Only the scenarios: a pack's scripts and its git history stay behind.
        shutil.copytree(
            root / "scenarios", staged / "scenarios", symlinks=False, ignore=_skip_links
        )
        shutil.rmtree(target, ignore_errors=True)
        staged.rename(target)
    config.patterns.dir = str(target)
    config.patterns.personas_only = True
    return next(v for v in view(config) if v["id"] == experience_id)


def _skip_links(folder: str, names: list[str]) -> list[str]:
    return [n for n in names if Path(folder, n).is_symlink()]


def remove(config: Any, experience_id: str) -> None:
    """Take an experience off this Mac. Rooms it made stay; they are ordinary rooms."""
    experience = _known(experience_id)
    pack = _pack_of(experience)
    if config.patterns.dir and Path(config.patterns.dir).expanduser().resolve() == pack.resolve():
        config.patterns.dir = None
    shutil.rmtree(pack.parent, ignore_errors=True)
