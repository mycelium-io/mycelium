#!/usr/bin/env python3
"""Redeploy mycelium across lab devices in a testbed.

Run this before a lab pyATS run when you want a clean reinstall pinned
to a specific mycelium git ref. The same logic also runs automatically
from the scenarios suite's ``CommonSetup`` when
``MYCELIUM_LAB_REDEPLOY=1`` is set — this script just makes it easy to
trigger from a developer laptop without firing up pyATS.

Usage
-----

    # Redeploy main on oclw3/4/5 with moderate cleanup
    python scripts/redeploy_lab.py \\
        --testbed testbeds/lab.yaml \\
        --ref main

    # Pin a SHA, nuclear wipe (re-enters LLM creds)
    python scripts/redeploy_lab.py \\
        --testbed testbeds/lab.yaml \\
        --ref a1b2c3d \\
        --cleanup nuclear \\
        --env LLM_MODEL anthropic/bedrock/claude-sonnet-4-6 \\
        --env-from-shell LLM_API_KEY \\
        --env-from-shell LLM_BASE_URL

    # Just verify the current install — no changes
    python scripts/redeploy_lab.py --testbed testbeds/lab.yaml --dry-run

Exit codes
----------

    0  every device redeployed successfully
    1  one or more devices failed (report includes which phases)
    2  CLI/argument error
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from libs.lab_redeploy import (  # noqa: E402 - sys.path tweak first
    LabCleanupMode,
    LabRedeployConfig,
    redeploy_testbed,
)

log = logging.getLogger(__name__)


def _parse_env_pair(arg: str) -> tuple[str, str]:
    if "=" not in arg:
        raise argparse.ArgumentTypeError(f"--env expects KEY=VALUE, got {arg!r}")
    key, _, value = arg.partition("=")
    return key, value


def _build_args() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="redeploy_lab",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--testbed",
        required=True,
        help="Path to pyATS testbed YAML (e.g. testbeds/lab.yaml).",
    )
    p.add_argument(
        "--ref",
        default=os.environ.get("MYCELIUM_LAB_REF", "main"),
        help="Mycelium git ref to install (branch/tag/SHA). Default: main.",
    )
    p.add_argument(
        "--repo-url",
        default=os.environ.get(
            "MYCELIUM_REPO_URL",
            "https://github.com/mycelium-io/mycelium.git",
        ),
        help="Override the repo URL (default: public origin).",
    )
    p.add_argument(
        "--cleanup",
        choices=[m.value for m in LabCleanupMode],
        default=os.environ.get("MYCELIUM_LAB_CLEANUP", LabCleanupMode.MODERATE.value),
        help="Cleanup aggressiveness. moderate keeps ~/.mycelium config; nuclear wipes everything including LLM creds.",
    )
    p.add_argument(
        "--source-dir",
        default="/tmp/mycelium-redeploy",  # noqa: S108 - deliberate; lab is shared-tenant
        help="Hub-side checkout location (default: /tmp/mycelium-redeploy).",
    )
    p.add_argument(
        "--include-ui",
        action="store_true",
        help="Also build mycelium-frontend:dev. Adds ~3min to build time.",
    )
    p.add_argument(
        "--env",
        action="append",
        type=_parse_env_pair,
        default=[],
        metavar="KEY=VALUE",
        help="Append KEY=VALUE to ~/.mycelium/.env on the hub. Repeatable. "
        "AVOID for secrets — values are passed through the shell argv; "
        "use --env-from-shell instead so they only leak via local env.",
    )
    p.add_argument(
        "--env-from-shell",
        action="append",
        default=[],
        metavar="KEY",
        help="Read KEY's value from this process's environment and "
        "append it to ~/.mycelium/.env on the hub. Repeatable. "
        "Preferred for LLM_API_KEY and similar secrets — never echoed.",
    )
    p.add_argument(
        "--skip-mycelium-install",
        action="store_true",
        help="Skip the final ``mycelium install -n --force`` step "
        "(useful when iterating on builds; the compose stack is up "
        "either way).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Load + print the redeploy plan but don't dispatch anything.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p


def _print_dry_run_plan(testbed: object, cfg: LabRedeployConfig) -> None:
    """Walk every device and print the commands the script would run.

    This is the operator's last sanity check before letting the redeploy
    actually touch real hardware. We import the private helpers from
    :mod:`libs.lab_redeploy` directly so the rendered commands stay in
    lockstep with what would dispatch for real — there's no second
    source of truth.
    """
    from libs import host_exec  # local import keeps the script importable in tests
    from libs.lab_redeploy import (
        _BUILD_HUB_IMAGES,
        _COMPOSE_DOWN,
        _COMPOSE_UP_HUB,
        _DATA_DIRS_WIPE,
        _backend_url,
        _clone_cmd,
        _role,
        _uv_install_cmd,
    )

    print()
    print("=" * 70)
    print("Dry-run plan (no commands will be dispatched)")
    print("=" * 70)

    devices = list(testbed.devices.values())  # type: ignore[attr-defined]
    hub_url = next(
        (_backend_url(d) for d in devices if _role(d) == "hub"),
        None,
    )

    # Order: hubs first, then spokes — mirrors redeploy_testbed.
    ordered = sorted(devices, key=lambda d: 0 if _role(d) == "hub" else 1)

    for dev in ordered:
        role = _role(dev)
        try:
            transport = host_exec.describe(dev)
        except Exception as exc:  # noqa: BLE001
            transport = f"<unresolvable: {exc}>"

        print()
        print(f"  Device: {dev.name}  role={role}  transport={transport}")
        if role == "hub":
            phases: list[tuple[str, str]] = [
                ("compose down + remove containers", _COMPOSE_DOWN),
                (f"wipe ~/.mycelium data ({cfg.cleanup_mode.value})", _DATA_DIRS_WIPE),
                (f"install CLI @ {cfg.ref}", _uv_install_cmd(cfg)),
                ("mycelium --version", "mycelium --version 2>&1"),
                (f"clone {cfg.ref} → {cfg.source_dir}", _clone_cmd(cfg)),
                ("build mycelium-backend + mycelium-collector", _BUILD_HUB_IMAGES.format(src=cfg.source_dir)),
                ("compose up -d (cfn + metrics profiles)", _COMPOSE_UP_HUB.format(src=cfg.source_dir)),
                ("backend health check (poll /health)", f"curl -sf {hub_url or '?'}/health"),
            ]
        else:
            phases = [
                ("compose down + remove containers", _COMPOSE_DOWN),
                (f"wipe ~/.mycelium data ({cfg.cleanup_mode.value})", _DATA_DIRS_WIPE),
                (f"install CLI @ {cfg.ref}", _uv_install_cmd(cfg)),
                ("mycelium --version", "mycelium --version 2>&1"),
                (
                    f"point CLI at {hub_url or '<derive from device>'}",
                    f"mycelium config set server.api_url {hub_url} && mycelium config apply",
                ),
                ("spoke can reach hub", f"curl -sf {hub_url}/health"),
            ]

        for label, cmd in phases:
            # Print the command on one line; truncate noisy long
            # commands but always show the first 120 chars so the
            # important bits (sub-commands, flags) are visible.
            single = " ".join(cmd.split())
            if len(single) > 200:
                single = single[:200] + " […]"
            print(f"    • {label}")
            print(f"      $ {single}")

    print()
    print("=" * 70)
    print("Re-run without --dry-run to execute.")
    print("=" * 70)


def _load_testbed(path: str):
    """Load a pyATS testbed lazily so the import cost is paid only when
    the caller actually runs against the lab.

    Returns a ``pyats.topology.Testbed`` or a fallback dict for tests.
    """
    try:
        from genie.testbed import load
    except ImportError as exc:  # pragma: no cover - genie always present in CI
        raise SystemExit(f"genie.testbed unavailable ({exc}). Install via `uv sync` first.") from exc
    return load(path)


def _build_env_overrides(ns: argparse.Namespace) -> dict[str, str]:
    """Merge ``--env`` and ``--env-from-shell`` into a single dict.

    Validates that ``--env-from-shell`` keys are present in the live env
    so the operator gets a clear failure rather than silently writing
    empty strings into ``.env``.
    """
    overrides: dict[str, str] = dict(ns.env)
    missing: list[str] = []
    for key in ns.env_from_shell:
        if key in os.environ:
            overrides[key] = os.environ[key]
        else:
            missing.append(key)
    if missing:
        raise SystemExit(f"--env-from-shell keys missing from environment: {', '.join(missing)}")
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = _build_args().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not Path(args.testbed).is_file():
        log.error("Testbed file not found: %s", args.testbed)
        return 2

    env_overrides = _build_env_overrides(args)

    cfg = LabRedeployConfig(
        ref=args.ref,
        repo_url=args.repo_url,
        cleanup_mode=LabCleanupMode(args.cleanup),
        source_dir=args.source_dir,
        include_ui=args.include_ui,
        skip_mycelium_install=args.skip_mycelium_install,
        env_overrides=env_overrides,
    )

    log.info("Redeploy plan:")
    log.info("  testbed:    %s", args.testbed)
    log.info("  ref:        %s", cfg.ref)
    log.info("  repo:       %s", cfg.repo_url)
    log.info("  cleanup:    %s", cfg.cleanup_mode.value)
    log.info("  source dir: %s", cfg.source_dir)
    log.info("  include UI: %s", cfg.include_ui)
    if env_overrides:
        # Log keys but not values — these are likely credentials.
        log.info("  env keys:   %s", ",".join(sorted(env_overrides)))

    testbed = _load_testbed(args.testbed)

    if args.dry_run:
        _print_dry_run_plan(testbed, cfg)
        return 0

    results = redeploy_testbed(testbed, cfg)

    print()
    print("=" * 70)
    print(f"Redeploy summary ({len(results)} device(s))")
    print("=" * 70)
    failed = 0
    for r in results:
        status = "OK" if r.success else f"FAIL ({r.error})"
        print(f"  {r.device_name:12s} [{r.role:5s}] {status}")
        for phase, ok, detail in r.logs:
            mark = "✓" if ok else "✗"
            extra = f" — {detail}" if detail else ""
            print(f"      {mark} {phase}{extra}")
        if not r.success:
            failed += 1
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
