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
