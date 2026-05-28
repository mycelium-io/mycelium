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
        import yaml
        try:
            with open(datafile_path) as f:
                data = yaml.safe_load(f)
            val = (data or {}).get("parameters", {}).get("max_failures")
            if val and int(val) > 0:
                return int(val)
        except Exception:
            pass

    return None
