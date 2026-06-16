#!/usr/bin/env python3
"""Provision the hermes lab — idempotent setup across all nodes.

Run this once before a CI run, or after a lab redeploy, to ensure every
node has mautrix installed, its Matrix user created, the hermes adapter
registered, and the gateway running.

Usage
-----

    # Provision all nodes (reads IPs from environment or defaults)
    python scripts/provision_hermes_lab.py

    # Provision specific nodes
    python scripts/provision_hermes_lab.py --nodes hub spoke1

    # Dry-run: show what would be checked/done without making changes
    python scripts/provision_hermes_lab.py --dry-run

    # Override the Matrix homeserver (e.g. in CI where it's remote)
    MATRIX_HOMESERVER=http://10.0.50.125:8008 python scripts/provision_hermes_lab.py

Environment variables
---------------------

    MATRIX_HOMESERVER   Matrix/Synapse URL (default: http://localhost:8008)
    OCLW4_IP            Hub IP (default: 10.0.50.125)
    OCLW3_IP            Spoke1 IP (default: 10.0.50.171)
    OCLW5_IP            Spoke2 IP (default: 10.0.50.142)
    SSH_KEY_PATH        SSH private key (default: ~/.ssh/ioc.pem)
    SSH_USER            SSH login user (default: ubuntu)

Exit codes
----------

    0   all nodes provisioned successfully
    1   one or more nodes failed
    2   argument error
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

from libs.hermes_lab import NodeConfig, ProvisionResult, check_prereqs, provision_lab

log = logging.getLogger(__name__)

_MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
_SSH_KEY = os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem")
_SSH_USER = os.environ.get("SSH_USER", "ubuntu")

# Node definitions — matrix_user follows the hermes-<node> convention
_ALL_NODES: list[NodeConfig] = [
    NodeConfig(
        name="hub",
        ssh_ip=os.environ.get("OCLW4_IP", "10.0.50.125"),
        ssh_user=_SSH_USER,
        ssh_key=_SSH_KEY,
        matrix_user="hermes-oclw4",
        matrix_homeserver=_MATRIX_HOMESERVER,
    ),
    NodeConfig(
        name="spoke1",
        ssh_ip=os.environ.get("OCLW3_IP", "10.0.50.171"),
        ssh_user=_SSH_USER,
        ssh_key=_SSH_KEY,
        matrix_user="hermes-oclw3",
        matrix_homeserver=_MATRIX_HOMESERVER,
    ),
    NodeConfig(
        name="spoke2",
        ssh_ip=os.environ.get("OCLW5_IP", "10.0.50.142"),
        ssh_user=_SSH_USER,
        ssh_key=_SSH_KEY,
        matrix_user="hermes-oclw5",
        matrix_homeserver=_MATRIX_HOMESERVER,
    ),
]

_NODE_MAP = {n.name: n for n in _ALL_NODES}


def _print_results(results: list[ProvisionResult]) -> int:
    print()
    print("=" * 70)
    print(f"Hermes lab provisioning ({len(results)} node(s))")
    print("=" * 70)
    failed = 0
    for r in results:
        status = "OK" if r.success else f"FAIL ({r.error})"
        print(f"  {r.node:10s}  {status}")
        for step, ok, detail in r.steps:
            mark = "✓" if ok else "✗"
            extra = f" — {detail}" if detail else ""
            print(f"    {mark} {step}{extra}")
        if not r.success:
            failed += 1
    print("=" * 70)
    return failed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="provision_hermes_lab",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--nodes",
        nargs="+",
        choices=list(_NODE_MAP),
        default=None,
        metavar="NODE",
        help=f"Nodes to provision (default: all). Choices: {', '.join(_NODE_MAP)}",
    )
    p.add_argument(
        "--check-only",
        action="store_true",
        help="Report missing prerequisites without making any changes.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --check-only.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    nodes = [_NODE_MAP[n] for n in args.nodes] if args.nodes else _ALL_NODES
    check_only = args.check_only or args.dry_run

    log.info("Matrix homeserver: %s", _MATRIX_HOMESERVER)
    log.info("Nodes: %s", ", ".join(n.name for n in nodes))

    if check_only:
        print("\nPrerequisite check (no changes will be made)")
        print("=" * 70)
        failed = 0
        for node in nodes:
            issues = check_prereqs(
                node.ssh_ip,
                node.ssh_user,
                node.ssh_key,
                matrix_homeserver=_MATRIX_HOMESERVER,
                matrix_user=node.matrix_user,
            )
            if issues:
                print(f"  {node.name:10s}  MISSING:")
                for issue in issues:
                    print(f"    ✗ {issue}")
                failed += 1
            else:
                print(f"  {node.name:10s}  OK")
        print("=" * 70)
        return 0 if failed == 0 else 1

    results = provision_lab(nodes, matrix_homeserver=_MATRIX_HOMESERVER)
    failed = _print_results(results)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
