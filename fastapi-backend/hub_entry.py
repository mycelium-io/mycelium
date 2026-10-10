# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The hub as one program, for the desktop app to bundle (``mycelium-hub``).

PyInstaller builds this into a standalone directory the app ships in its
Resources; ``mycelium desktop serve`` starts it in place of ``uvicorn``
from a checkout. Settings come from the environment, as in the container.
"""

import argparse
import multiprocessing


def main() -> None:
    import uvicorn

    from app.main import app

    parser = argparse.ArgumentParser(prog="mycelium-hub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    # The voice worker (app/services/voice_worker.py) is this same program,
    # started again by multiprocessing; this hands it to its job before the
    # hub's own startup, which is also why the app is imported in main().
    multiprocessing.freeze_support()
    main()
