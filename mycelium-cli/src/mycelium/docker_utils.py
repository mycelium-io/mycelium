# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Generate .env files from config.toml — makes .env a derived artifact.

The canonical configuration lives in ~/.mycelium/config.toml.  This module
renders a Docker-compatible .env from the [llm], [runtime], and [server]
sections so that ``docker compose`` picks up the same values without users
having to maintain two files.

One field deliberately *isn't* in config.toml: ``MYCELIUM_IMAGE_TAG``.  It's
operational state — set as a side effect of ``mycelium pull --version`` and
consumed only by compose's ``${MYCELIUM_IMAGE_TAG:-latest}`` substitution.
We round-trip it through the existing .env on regeneration so that
``mycelium config apply`` doesn't silently roll users back to ``:latest``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


# Operator-managed keys: not derivable from config.toml, but preserved across
# ``mycelium config apply`` so that side-effecting commands like
# ``mycelium pull --version`` don't get clobbered.  Add new entries here only
# when the key has no natural home in MyceliumConfig (i.e., it's runtime/ops
# state, not user-tunable configuration).
_OPERATOR_MANAGED_KEYS: tuple[str, ...] = ("MYCELIUM_IMAGE_TAG",)


def _read_operator_managed_keys(env_path: Path | None) -> dict[str, str]:
    """Extract operator-managed values from an existing ``.env``.

    Returns an empty dict if ``env_path`` is None or the file doesn't exist.
    Used by ``write_env_file`` to preserve pins across regeneration and by
    ``mycelium up`` to surface the effective tag at startup.

    Parsing is intentionally permissive (matches ``_patch_env_image_tag``'s
    behaviour): blank/commented lines are skipped, ``KEY=value`` is split on
    the first ``=``, and surrounding whitespace is stripped.
    """
    if env_path is None or not env_path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in _OPERATOR_MANAGED_KEYS:
                out[key] = value.strip()
    except OSError:
        # Best-effort: callers always have a sensible fallback.
        return {}
    return out


def read_pinned_image_tag(env_path: Path | None) -> str | None:
    """Return the ``MYCELIUM_IMAGE_TAG`` value from ``env_path``, or None.

    Public helper so that ``mycelium up`` can surface the effective tag
    without rebuilding the parser.
    """
    return _read_operator_managed_keys(env_path).get("MYCELIUM_IMAGE_TAG")


def generate_env_file(
    config: MyceliumConfig,
    *,
    image_tag: str | None = None,
) -> str:
    """Render a .env string from the current MyceliumConfig.

    Parameters
    ----------
    config
        Canonical mycelium config — drives every key in the rendered file
        except the operator-managed pins below.
    image_tag
        Optional ``MYCELIUM_IMAGE_TAG`` value to emit verbatim.  Passed in by
        ``write_env_file`` after round-tripping the previous .env so that
        ``mycelium pull --version``'s pin survives ``mycelium config apply``.
        Pass ``None`` to omit the line entirely — compose then falls through
        to its ``${MYCELIUM_IMAGE_TAG:-latest}`` default.

    The output is suitable for ``docker compose --env-file``.  Keys that have
    no value in config are emitted as empty (``KEY=``) so that downstream
    compose variable substitution falls through to its defaults.
    """
    lines: list[str] = [
        "# Auto-generated from ~/.mycelium/config.toml — do not edit manually.",
        "# Regenerate with: mycelium config apply",
        "",
        "# ── Backend ──────────────────────────────────────────────────────────────",
        f"MYCELIUM_BACKEND_PORT={config.runtime.backend_port}",
        f"MYCELIUM_UI_PORT={config.runtime.frontend_port}",
        f"MYCELIUM_METRICS_PORT={config.runtime.collector_port}",
        f"MYCELIUM_DATA_DIR={config.runtime.data_dir or str(Path.home() / '.mycelium')}",
        "",
        "# ── LLM ──────────────────────────────────────────────────────────────────",
        f"LLM_MODEL={config.llm.model or ''}",
        f"LLM_API_KEY={config.llm.api_key or ''}",
        # Only emit LLM_BASE_URL when actually set — an empty value causes the
        # OpenAI SDK to reject it as UnsupportedProtocol in downstream
        # services that don't have the backend's validator.
        f"LLM_BASE_URL={config.llm.base_url}"
        if config.llm.base_url
        else "# LLM_BASE_URL not set — using provider default",
        "",
    ]

    # ── Operator-managed pins (preserved across `mycelium config apply`) ─────
    # Anything in this block is NOT derived from config.toml; it's set as a
    # side effect of a CLI command (currently only `mycelium pull --version`,
    # which writes MYCELIUM_IMAGE_TAG via _patch_env_image_tag).  Emitted last
    # so that compose variable substitution gets a stable, late-binding value.
    if image_tag is not None:
        lines.extend(
            [
                "# ── Operator-managed pins (managed by `mycelium pull --version`) ────────",
                f"MYCELIUM_IMAGE_TAG={image_tag}",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def write_env_file(config: MyceliumConfig, env_path: Path | None = None) -> Path:
    """Write (or overwrite) the .env file derived from config.toml.

    Preserves operator-managed pins (currently ``MYCELIUM_IMAGE_TAG``) from
    the existing .env so that ``mycelium config apply`` doesn't silently
    roll users back to ``:latest`` after a ``mycelium pull --version``.

    Returns the path that was written.
    """
    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    preserved = _read_operator_managed_keys(env_path)
    rendered = generate_env_file(config, image_tag=preserved.get("MYCELIUM_IMAGE_TAG"))
    env_path.write_text(rendered, encoding="utf-8")
    return env_path
