# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the runner did, in ``runner.log``: timestamped, rotated, wherever it runs.

The runner writes here whether it runs from ``mycelium runner`` or inside the
Mac app, so the file is the one place to read what it did: each wake, each
job, each question asked, and each herdr or hub call that failed or was slow.
Successful calls are left out.

Everything logs through ``log`` or a child of it (``mycelium.runner.herdr``,
``mycelium.runner.hub``). Outside a runner nothing opens the file, so the
lines go nowhere: ``mycelium herdr sync`` from a terminal writes no file.
"""

from __future__ import annotations

import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("mycelium.runner")
log.addHandler(logging.NullHandler())
log.propagate = False

#: The size ``runner.log`` rotates at, and how many old files are kept.
MAX_BYTES = 1_000_000
BACKUPS = 3
#: A herdr or hub call that took longer than this is logged even when it worked.
SLOW_S = 5.0


def open_log(path: Path) -> None:
    """Write the runner's lines to ``path``, rotated. One file per process."""
    target = path.resolve()
    for handler in list(log.handlers):
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename) == target:
                return
            log.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(target, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)-7s [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def ms(since: float) -> int:
    """Milliseconds since ``since``, a ``time.monotonic()``."""
    return round((time.monotonic() - since) * 1000)


_failing: dict[str, str] = {}
_failing_lock = threading.Lock()


def failing(logger: logging.Logger, key: str, text: str) -> None:
    """Log a failure when it starts or changes, not on every pass while it lasts."""
    with _failing_lock:
        if _failing.get(key) == text:
            return
        _failing[key] = text
    logger.warning(text)


def recovered(logger: logging.Logger, key: str) -> None:
    """Log that what :func:`failing` reported under ``key`` works again."""
    with _failing_lock:
        if _failing.pop(key, None) is None:
            return
    logger.info("%s works again", key)


def slow(logger: logging.Logger, what: str, since: float) -> None:
    """Log ``what`` when it took longer than :data:`SLOW_S`."""
    took = ms(since)
    if took > SLOW_S * 1000:
        logger.warning("%s was slow: %dms", what, took)
