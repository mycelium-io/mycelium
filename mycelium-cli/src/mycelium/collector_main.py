"""Entry point for running the OTLP collector as a background process."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument(
        "--output", type=str, default=str(Path.home() / ".mycelium" / "metrics.json")
    )
    parser.add_argument(
        "--backend-url", type=str, default="http://localhost:8000",
        help="Mycelium backend URL for polling /api/metrics",
    )

    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error(f"Invalid port {args.port} (must be 1–65535)")

    from mycelium.collector import run

    run(args.port, Path(args.output), backend_api_url=args.backend_url)


if __name__ == "__main__":
    main()
