# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Auto-reindex: startup scan + file watcher.

On startup, incrementally scans all rooms and re-indexes changed files.
While running, watches ~/.mycelium/rooms/ for file changes and auto-indexes.
"""

import asyncio
import logging
import time
from pathlib import Path

from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

_observer = None
_loop: asyncio.AbstractEventLoop | None = None


async def startup_scan() -> None:
    """Incremental scan of all rooms on startup."""
    from app.database import async_session_maker
    from app.services.indexer import index_all_rooms

    try:
        async with async_session_maker() as db:
            stats = await index_all_rooms(db)
            logger.info(
                "Startup scan: %d rooms, %d indexed, %d unchanged",
                stats["rooms"],
                stats["total_indexed"],
                stats["total_skipped"],
            )
    except Exception:
        logger.warning("Startup scan failed (non-fatal)", exc_info=True)


def start_watcher() -> None:
    """Start watching ~/.mycelium/rooms/ for file changes. Non-fatal if watchdog missing."""
    global _observer, _loop

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.info("watchdog not installed — file watcher disabled (pip install watchdog)")
        return

    _loop = asyncio.get_running_loop()

    rooms_dir = get_data_dir() / "rooms"
    rooms_dir.mkdir(parents=True, exist_ok=True)

    # Temp file patterns to ignore
    _ignore_suffixes = {".swp", ".swo", ".tmp", "~"}
    _ignore_prefixes = {".#", "#"}

    class MemoryFileHandler(FileSystemEventHandler):
        def __init__(self) -> None:
            self._debounce: dict[str, float] = {}

        def _should_ignore(self, path: str) -> bool:
            name = Path(path).name
            if not path.endswith(".md"):
                return True
            return any(name.endswith(s) for s in _ignore_suffixes) or any(
                name.startswith(p) for p in _ignore_prefixes
            )

        def on_modified(self, event):  # type: ignore[override]
            if not event.is_directory and not self._should_ignore(event.src_path):
                self._schedule(event.src_path)

        def on_created(self, event):  # type: ignore[override]
            if not event.is_directory and not self._should_ignore(event.src_path):
                self._schedule(event.src_path)

        def on_deleted(self, event):  # type: ignore[override]
            if not event.is_directory and not self._should_ignore(event.src_path):
                self._schedule(event.src_path)

        def _schedule(self, path_str: str) -> None:
            now = time.time()
            if path_str in self._debounce and now - self._debounce[path_str] < 2.0:
                return
            self._debounce[path_str] = now

            # Parse room_name and key from path
            try:
                path = Path(path_str)
                rel = path.relative_to(rooms_dir)
                parts = rel.parts
                if len(parts) < 2:
                    return
                room_name = parts[0]
                key = str(Path(*parts[1:]))
                if key.endswith(".md"):
                    key = key[:-3]
            except (ValueError, IndexError):
                return

            if _loop is not None:
                asyncio.run_coroutine_threadsafe(_reindex_file(room_name, key), _loop)

    observer = Observer()
    observer.schedule(MemoryFileHandler(), str(rooms_dir), recursive=True)
    observer.daemon = True
    observer.start()
    _observer = observer
    logger.info("File watcher started on %s", rooms_dir)


def stop_watcher() -> None:
    """Stop the file watcher."""
    global _observer
    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None
        logger.info("File watcher stopped")


async def _reindex_file(room_name: str, key: str) -> None:
    """Reindex a single file triggered by the watcher."""
    from app.database import async_session_maker
    from app.services.indexer import index_single_file

    try:
        async with async_session_maker() as db:
            indexed = await index_single_file(room_name, key, db)
            if indexed:
                logger.debug("Auto-indexed %s/%s", room_name, key)
    except Exception:
        logger.warning("Auto-reindex failed for %s/%s", room_name, key, exc_info=True)
