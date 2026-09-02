"""Shared utilities for pyATS job files."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# Ensure project root is on PYTHONPATH for all job executions
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def no_cleanup() -> bool:
    """Return True when MYCELIUM_E2E_NO_CLEANUP=1 is set.

    When True, every testcase ``@aetest.cleanup`` section and every
    ``CommonCleanup`` subsection should call ``self.skipped()`` and return
    without performing any teardown.  Room deletion defined in CommonCleanup
    is left in place — it simply won't run.  Use this during development to
    preserve the full room/session/DB state for post-test inspection.

    The presuite hygiene stale-room sweep in ``CommonSetup`` is also skipped
    when this flag is set, so rooms from a previous no-cleanup run are not
    silently deleted at the start of the next one.
    """
    return os.environ.get("MYCELIUM_E2E_NO_CLEANUP", "").lower() in {"1", "true", "yes"}


def keep_rooms() -> bool:
    """Return True when MYCELIUM_E2E_KEEP_ROOMS=1 is set.

    When True, room deletion in both testcase ``@aetest.cleanup`` sections
    and suite ``CommonCleanup`` subsections is skipped.  Agents and other
    non-room teardown still run.  Use this to preserve room/session state
    for post-test inspection without suppressing the full cleanup cycle.
    """
    return os.environ.get("MYCELIUM_E2E_KEEP_ROOMS", "").lower() in {"1", "true", "yes"}


def get_project_root() -> str:
    return _ROOT


def get_datafile(env_var: str = "MYCELIUM_DATAFILE", default: str = "base_datafile.yaml") -> str:
    """Resolve the datafile path from env var or default."""
    datafile = os.environ.get(env_var, default)
    if not os.path.isabs(datafile):
        datafile = os.path.join(_ROOT, "data", datafile)
    return datafile


def resolve_backend_url(datafile_path: str | None = None) -> str:
    """Resolve the mycelium backend URL for use outside a running suite.

    Resolution order:
    1. ``MYCELIUM_BACKEND_URL`` env var
    2. ``parameters.topology.backend.base_url`` from the datafile (with
       ``%ENV{VAR, default}`` expansion)
    3. Hard-coded default: ``http://localhost:8000``
    """
    from_env = os.environ.get("MYCELIUM_BACKEND_URL", "").strip()
    if from_env:
        return from_env

    if datafile_path:
        raw = _read_datafile_param(datafile_path, "topology")
        if isinstance(raw, dict):
            raw_url = (raw.get("backend") or {}).get("base_url", "")
            if raw_url and raw_url.startswith("%ENV{"):
                inner = raw_url[5:-1]
                parts = inner.split(",", 1)
                var = parts[0].strip()
                default = parts[1].strip() if len(parts) > 1 else ""
                raw_url = os.environ.get(var, default)
            if raw_url:
                return raw_url.strip()

    return "http://localhost:8000"


# Room prefixes used by all suites — kept in one place so the SIGINT handler
# and CommonCleanup sweep the same set of names.
E2E_ROOM_PREFIXES: tuple[str, ...] = ("e2e-", "dist-e2e-", "scn-")


def install_job_sigint_cleanup(
    backend_url: str,
    prefixes: tuple[str, ...] = E2E_ROOM_PREFIXES,
) -> None:
    """Install a SIGINT handler that sweeps e2e rooms before the job exits.

    Addresses the job-level Ctrl-C gap: pyATS guarantees ``CommonCleanup``
    runs when Ctrl-C fires *inside* a running suite, but if the interrupt
    hits between ``run()`` calls in the job's ``main()``, subsequent suites
    and their cleanups are skipped entirely.  This handler fires the moment
    SIGINT is received, deletes rooms with the known e2e prefixes via the
    backend API, then chains to pyATS's own handler so it can finish its
    graceful shutdown.

    Call once near the top of ``main(runtime)`` before the first ``run()``.
    """
    import signal

    prev_handler = signal.getsignal(signal.SIGINT)

    def _handler(signum: int, frame: Any) -> None:
        # Restore default immediately so a second Ctrl-C force-kills.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        logging.getLogger(__name__).warning(
            "SIGINT received — sweeping e2e rooms from %s before exit", backend_url
        )
        try:
            from libs.mycelium_api import MyceliumAPI

            api = MyceliumAPI(base_url=backend_url)
            for prefix in prefixes:
                deleted = api.cleanup_rooms(prefix)
                if deleted:
                    logging.getLogger(__name__).warning(
                        "Deleted %d '%s*' rooms on interrupt", deleted, prefix
                    )
        except Exception as exc:  # noqa: BLE001 — best-effort, never block shutdown
            logging.getLogger(__name__).warning("Room sweep on interrupt failed: %s", exc)

        # Chain to pyATS's own SIGINT handler so it can abort cleanly.
        if callable(prev_handler) and prev_handler not in (
            signal.SIG_DFL,
            signal.SIG_IGN,
        ):
            prev_handler(signum, frame)  # type: ignore[operator]
        else:
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handler)
    logging.getLogger(__name__).info(
        "Installed SIGINT cleanup handler (backend=%s prefixes=%s)", backend_url, prefixes
    )


def _read_datafile_param(datafile_path: str, key: str, _depth: int = 0):
    """Read a parameter from a datafile, following ``extends:`` directives.

    pyATS datafiles support ``extends: base.yaml`` for inheritance, but
    ``yaml.safe_load()`` doesn't resolve it.  Walk the chain (max 5 deep)
    and return the first matching ``parameters.<key>`` value found.
    """
    if _depth > 5 or not os.path.isfile(datafile_path):
        return None

    import yaml

    try:
        with open(datafile_path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return None

    val = data.get("parameters", {}).get(key)
    if val is not None:
        return val

    extends = data.get("extends")
    if extends:
        parent = os.path.join(os.path.dirname(datafile_path), extends)
        return _read_datafile_param(parent, key, _depth + 1)

    return None
