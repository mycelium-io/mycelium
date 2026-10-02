# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Experiences added from a file: what the desktop app's Experiences section does.

A pack arrives as a zip or a folder; only its scenarios are kept, the hub is
pointed at them with personas only, and a zip that would put anything outside
its folder, carries a link, or holds no scenarios is refused with a reason.
"""

from __future__ import annotations

import json
import stat
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from mycelium.config import MyceliumConfig
from mycelium.desktop import experiences as xp

SCENARIO = "pattern: approval-gate-agent\n"
_CONTRACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "experiences.json"


def test_the_catalogue_is_the_contracts():
    contract = json.loads(_CONTRACT.read_text())
    assert [asdict(x) for x in xp.CATALOG] == contract["experiences"]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(xp, "experiences_dir", lambda: tmp_path / "experiences")
    return tmp_path


def pack_zip(path: Path, entries: dict[str, str], prefix: str = "patterns-main/") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in entries.items():
            zf.writestr(prefix + name, text)
    return path


def test_a_pack_from_a_zip_is_added_and_the_hub_pointed_at_it(tmp_path):
    archive = pack_zip(
        tmp_path / "pack.zip",
        {
            "scenarios/approval-gate-agent/scenario.yaml": SCENARIO,
            "scenarios/supervisor-worker/scenario.yaml": SCENARIO,
            "scripts/validate.py": "print('not copied')",
        },
    )
    config = MyceliumConfig()
    added = xp.add(config, "patterns-explorer", archive)

    assert added["added"] and added["active"]
    assert added["scenarios"] == 2
    pack = tmp_path / "experiences" / "patterns-explorer" / "pack"
    assert config.patterns.dir == str(pack)
    assert config.patterns.personas_only is True
    assert sorted(p.name for p in pack.iterdir()) == ["scenarios"]  # the scripts stay behind


def test_a_folder_works_too_and_adding_again_replaces_it(tmp_path):
    folder = tmp_path / "patterns"
    (folder / "scenarios" / "one").mkdir(parents=True)
    (folder / "scenarios" / "one" / "scenario.yaml").write_text(SCENARIO)
    config = MyceliumConfig()
    xp.add(config, "patterns-explorer", folder)
    (folder / "scenarios" / "two").mkdir()
    (folder / "scenarios" / "two" / "scenario.yaml").write_text(SCENARIO)
    assert xp.add(config, "patterns-explorer", folder)["scenarios"] == 2


@pytest.mark.parametrize(
    ("entries", "prefix", "why"),
    [
        ({"../escape.yaml": "x"}, "", "outside its folder"),
        ({"README.md": "no scenarios here"}, "", "no scenarios folder"),
        ({"scenarios/README.md": "x"}, "", "no scenarios/<name>/scenario.yaml"),
    ],
)
def test_a_zip_that_isnt_a_plain_pack_is_refused(tmp_path, entries, prefix, why):
    archive = pack_zip(tmp_path / "bad.zip", entries, prefix)
    with pytest.raises(xp.ExperienceError, match=why):
        xp.add(MyceliumConfig(), "patterns-explorer", archive)
    assert not (tmp_path / "experiences" / "patterns-explorer" / "pack").exists()


def test_a_zip_with_a_link_is_refused(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("scenarios/a/scenario.yaml", SCENARIO)
        link = zipfile.ZipInfo("scenarios/a/notes")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "/etc/passwd")
    with pytest.raises(xp.ExperienceError, match="link"):
        xp.add(MyceliumConfig(), "patterns-explorer", archive)


def test_a_file_that_isnt_a_zip_or_an_unknown_experience_is_refused(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    with pytest.raises(xp.ExperienceError, match="isn't a zip"):
        xp.add(MyceliumConfig(), "patterns-explorer", other)
    with pytest.raises(xp.ExperienceError, match="no experience called"):
        xp.add(MyceliumConfig(), "nope", other)


def test_removing_one_takes_its_content_and_unpoints_the_hub(tmp_path):
    archive = pack_zip(tmp_path / "pack.zip", {"scenarios/a/scenario.yaml": SCENARIO})
    config = MyceliumConfig()
    xp.add(config, "patterns-explorer", archive)
    xp.remove(config, "patterns-explorer")
    assert config.patterns.dir is None
    assert xp.view(config)[0]["added"] is False
