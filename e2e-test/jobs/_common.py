"""Shared utilities for pyATS job files."""

import os
import sys

# Ensure project root is on PYTHONPATH for all job executions
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def get_project_root() -> str:
    return _ROOT


def get_suite_path(suite_name: str) -> str:
    return os.path.join(_ROOT, "suites", suite_name)


def get_datafile(env_var: str = "MYCELIUM_DATAFILE", default: str = "base_datafile.yaml") -> str:
    """Resolve the datafile path from env var or default."""
    datafile = os.environ.get(env_var, default)
    if not os.path.isabs(datafile):
        datafile = os.path.join(_ROOT, "data", datafile)
    return datafile


def get_testbed_file(
    env_var: str = "MYCELIUM_TESTBED_FILE",
    default: str | None = None,
) -> str | None:
    """Resolve the pyATS testbed file path from env var or default.

    Returns ``None`` when neither the env var nor the default is set —
    pyATS treats a missing testbed as "no devices" which is fine for
    legacy jobs that don't need device resolution. The new scenario
    suite always passes a testbed file via CLI (``--testbed-file``)
    so this helper is mostly used for documentation / fallback paths.

    A bare filename (no ``/``) is resolved against ``testbeds/`` so
    callers can pass ``"compose.yaml"`` interchangeably with
    ``"testbeds/compose.yaml"``.
    """
    raw = os.environ.get(env_var, default)
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    if os.sep in raw or raw.startswith("testbeds/"):
        return os.path.join(_ROOT, raw)
    return os.path.join(_ROOT, "testbeds", raw)


def ensure_tier_env(default: str = "all") -> str:
    """Ensure ``MYCELIUM_E2E_TIERS`` is set; return the effective value.

    Job files use this to *set* the tier when one isn't provided by
    the workflow (``pr_job.py`` defaults to ``"pr"``,
    ``nightly_e2e_job.py`` defaults to ``"pr,nightly"``) — the env var
    is the source of truth used by
    :func:`testcases.scenarios.active_tiers` so the import-time class
    generation in :mod:`suites.scenarios_suite` picks up the right
    rows.

    Setting via env (rather than passing through ``run()``) keeps the
    contract symmetrical between job-driven and ad-hoc runs (``pyats
    run job …`` and ``MYCELIUM_E2E_TIERS=pr pyats run job …``).
    """
    existing = os.environ.get("MYCELIUM_E2E_TIERS")
    if existing:
        return existing
    os.environ["MYCELIUM_E2E_TIERS"] = default
    return default


def get_max_failures(datafile_path: str | None = None) -> int | None:
    """Read max_failures from the datafile or MAX_FAILURES env var.

    Returns None when unset or zero (run all tests regardless).
    pyATS ``run(max_failures=N)`` aborts the script after N testcase failures.
    """
    env_val = os.environ.get("MAX_FAILURES", "")
    if env_val:
        try:
            n = int(env_val)
            return n if n > 0 else None
        except ValueError:
            pass

    if datafile_path and os.path.isfile(datafile_path):
        val = _read_datafile_param(datafile_path, "max_failures")
        if val is not None:
            try:
                n = int(val)
                return n if n > 0 else None
            except (ValueError, TypeError):
                pass

    return None


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
