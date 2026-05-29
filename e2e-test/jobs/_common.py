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
