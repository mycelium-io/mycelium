# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Regression tests for the ``MYCELIUM_IMAGE_TAG`` round-trip behaviour.

Before this fix, ``write_env_file`` would silently drop the pin set by
``mycelium pull --version <X>``, causing ``mycelium config apply`` (and any
other path that regenerated .env) to roll users back to ``:latest`` on the
next ``mycelium up``.  We caught this only when a test environment kept
running 1.0.13 while we thought we were on 1.0.14rc3.

The contract:

  1. ``generate_env_file(config)`` (no image_tag) MUST NOT emit
     ``MYCELIUM_IMAGE_TAG`` — compose's ``:latest`` default applies.
  2. ``generate_env_file(config, image_tag="X")`` MUST emit the pin verbatim
     in a clearly-labelled "Operator-managed pins" section.
  3. ``write_env_file`` MUST round-trip the pin: a pre-existing pin in
     ``.env`` is preserved when the file is regenerated from config.toml.
  4. ``read_pinned_image_tag`` MUST return ``None`` for missing files /
     missing key, and the value verbatim when present.
"""

from __future__ import annotations

from pathlib import Path

from mycelium.config import MyceliumConfig
from mycelium.docker_utils import (
    generate_env_file,
    read_pinned_image_tag,
    write_env_file,
)


def _parse_env(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


# ── generate_env_file: emit semantics ────────────────────────────────────────


def test_generate_omits_pin_when_image_tag_is_none() -> None:
    """No pin → no line. Compose falls through to ${MYCELIUM_IMAGE_TAG:-latest}."""
    env = _parse_env(generate_env_file(MyceliumConfig()))
    assert "MYCELIUM_IMAGE_TAG" not in env


def test_generate_emits_pin_when_image_tag_is_supplied() -> None:
    blob = generate_env_file(MyceliumConfig(), image_tag="1.0.14rc3")
    env = _parse_env(blob)
    assert env["MYCELIUM_IMAGE_TAG"] == "1.0.14rc3"
    # Sanity: lives in the dedicated section, not buried mid-file.
    assert "Operator-managed pins" in blob


def test_generate_emits_pin_even_for_explicit_latest() -> None:
    """`mycelium pull --version=latest` is an explicit unpin — surface it
    verbatim rather than silently dropping the line, so the user can see
    intent if they `cat .env`.
    """
    env = _parse_env(generate_env_file(MyceliumConfig(), image_tag="latest"))
    assert env["MYCELIUM_IMAGE_TAG"] == "latest"


# ── write_env_file: round-trip semantics ─────────────────────────────────────


def test_write_preserves_existing_pin(tmp_path: Path) -> None:
    """The #287-class bug we just fixed: ``mycelium config apply`` must NOT
    silently drop a pin set by ``mycelium pull --version``.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MYCELIUM_DB_PASSWORD=password\nMYCELIUM_IMAGE_TAG=1.0.14rc3\n",
        encoding="utf-8",
    )

    write_env_file(MyceliumConfig(), env_path=env_path)

    env = _parse_env(env_path.read_text(encoding="utf-8"))
    assert env["MYCELIUM_IMAGE_TAG"] == "1.0.14rc3", (
        "config apply silently rolled the pin back to :latest (regression of "
        "the v1.0.14rc3 mismatch incident)"
    )


def test_write_without_existing_pin_omits_line(tmp_path: Path) -> None:
    """First-time install / no pin → no MYCELIUM_IMAGE_TAG line emitted."""
    env_path = tmp_path / ".env"
    # No file yet.
    write_env_file(MyceliumConfig(), env_path=env_path)

    env = _parse_env(env_path.read_text(encoding="utf-8"))
    assert "MYCELIUM_IMAGE_TAG" not in env


def test_write_preserves_pin_across_multiple_regenerations(tmp_path: Path) -> None:
    """Defence-in-depth: round-trip should be stable even if the user runs
    ``mycelium config apply`` repeatedly.
    """
    env_path = tmp_path / ".env"
    env_path.write_text("MYCELIUM_IMAGE_TAG=0.9.2rc4\n", encoding="utf-8")

    cfg = MyceliumConfig()
    for _ in range(3):
        write_env_file(cfg, env_path=env_path)

    env = _parse_env(env_path.read_text(encoding="utf-8"))
    assert env["MYCELIUM_IMAGE_TAG"] == "0.9.2rc4"


def test_write_ignores_non_managed_keys_in_existing_env(tmp_path: Path) -> None:
    """Round-trip is intentionally narrow — only the operator-managed pin
    survives.  Anything else in .env is fair game for regeneration from
    config.toml (that's the whole point of materialising it).
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MYCELIUM_IMAGE_TAG=1.0.14rc3\nSTALE_USER_EDIT=should-be-dropped\n",
        encoding="utf-8",
    )

    write_env_file(MyceliumConfig(), env_path=env_path)

    env = _parse_env(env_path.read_text(encoding="utf-8"))
    assert env["MYCELIUM_IMAGE_TAG"] == "1.0.14rc3"
    assert "STALE_USER_EDIT" not in env


# ── read_pinned_image_tag: callers in mycelium up rely on this ──────────────


def test_read_pinned_image_tag_returns_value_when_present(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MYCELIUM_DB_PASSWORD=password\nMYCELIUM_IMAGE_TAG=1.0.14rc3\n",
        encoding="utf-8",
    )
    assert read_pinned_image_tag(env_path) == "1.0.14rc3"


def test_read_pinned_image_tag_returns_none_when_missing(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MYCELIUM_DB_PASSWORD=password\n", encoding="utf-8")
    assert read_pinned_image_tag(env_path) is None


def test_read_pinned_image_tag_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert read_pinned_image_tag(tmp_path / "no-such-file.env") is None


def test_read_pinned_image_tag_tolerates_blank_and_comment_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\n\n  # MYCELIUM_IMAGE_TAG=ignored\nMYCELIUM_IMAGE_TAG=1.0.14rc3 \n",
        encoding="utf-8",
    )
    assert read_pinned_image_tag(env_path) == "1.0.14rc3"
