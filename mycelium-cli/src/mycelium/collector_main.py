# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Entry point for the OTLP collector (used by Dockerfile.collector)."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path


def _default_output() -> str:
    data_dir = Path(os.environ.get("MYCELIUM_DATA_DIR") or Path.home() / ".mycelium")
    return str(data_dir / "metrics" / "metrics.json")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--output", type=str, default=_default_output())
    parser.add_argument(
        "--backend-url",
        type=str,
        default="http://localhost:8000",
        help="Mycelium backend URL for polling /api/observability",
    )
    parser.add_argument(
        "--no-backend",
        action="store_true",
        default=False,
        help="Skip backend polling and Prometheus scraping (spoke-local OTLP-only mode)",
    )

    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error(f"Invalid port {args.port} (must be 1–65535)")

    from mycelium.collector import run
    from mycelium.config import MyceliumConfig

    # Resolve scrape targets (auto-derived from runtime.cfn_* URLs, plus any
    # explicit [[metrics.scrape]] entries). Best-effort: failures here must
    # not prevent the OTLP receiver from starting.
    scrape_targets: list[dict] = []
    try:
        scrape_targets = MyceliumConfig.load().resolve_scrape_targets()
    except Exception as exc:  # noqa: BLE001
        logging.warning("Could not resolve scrape targets: %s", exc)

    run(
        args.port,
        Path(args.output),
        backend_api_url=args.backend_url,
        scrape_targets=scrape_targets,
        no_backend=args.no_backend,
    )


if __name__ == "__main__":
    main()
