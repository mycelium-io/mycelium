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

    args = parser.parse_args()

    from mycelium.collector import run

    run(args.port, Path(args.output))


if __name__ == "__main__":
    main()
