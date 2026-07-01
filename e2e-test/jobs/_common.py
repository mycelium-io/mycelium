"""Shared utilities for pyATS job files."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from pyats.datastructures.logic import Or

# Ensure project root is on PYTHONPATH for all job executions
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# Runtime / testbed contract
# --------------------------
# Scenario rows name *logical* hosts (hub, spoke1, spoke2). **Jobs own
# runtime** — each job declares a default and which runtimes it permits.
#
# Resolution order (first match wins):
#
#   1. ``--testbed-file``  →  pyATS ``runtime.testbed`` (explicit override)
#   2. ``MYCELIUM_E2E_RUNTIME=compose|lab``  (operator / workflow)
#   3. ``GITHUB_ACTIONS`` set  →  compose (CI auto-detect)
#   4. Job ``_DEFAULT_RUNTIME`` fallback
#
# The chosen runtime maps to a testbed YAML:
#   compose  → testbeds/compose.yaml  (docker exec on runner)
#   lab      → testbeds/lab.yaml      (SSH to oclw4/3/5)
#
# Scenario rows do not carry a runtime field.

RUNTIME_ENV_VAR = "MYCELIUM_E2E_RUNTIME"

RUNTIME_COMPOSE = "compose"
RUNTIME_LAB = "lab"

RUNTIMES_ALL = frozenset({RUNTIME_COMPOSE, RUNTIME_LAB})
RUNTIME_LAB_ONLY = frozenset({RUNTIME_LAB})

TESTBED_COMPOSE = "testbeds/compose.yaml"
TESTBED_LAB = "testbeds/lab.yaml"

# ``testbed.name`` values from ``testbeds/*.yaml`` — used when pyATS has
# already loaded a topology object (``runtime.testbed`` or ``run(testbed=)``).
TESTBED_NAME_COMPOSE = "mycelium-compose"
TESTBED_NAME_LAB = "mycelium-lab"


class JobRuntimeMismatchError(RuntimeError):
    """Active testbed/runtime is not permitted for this job."""


class InvalidE2ERuntimeError(ValueError):
    """MYCELIUM_E2E_RUNTIME is set to an unsupported value."""


def testbed_path_for_runtime(runtime: str) -> str:
    """Map a runtime label to the canonical testbed YAML path."""
    if runtime == RUNTIME_COMPOSE:
        return TESTBED_COMPOSE
    if runtime == RUNTIME_LAB:
        return TESTBED_LAB
    raise InvalidE2ERuntimeError(
        f"unsupported runtime {runtime!r}; expected {RUNTIME_COMPOSE!r} or {RUNTIME_LAB!r}",
    )


def active_e2e_runtime(job_default: str) -> str:
    """Pick compose vs lab from env, CI auto-detect, or the job default."""
    explicit = os.environ.get(RUNTIME_ENV_VAR, "").strip().lower()
    if explicit:
        if explicit not in RUNTIMES_ALL:
            raise InvalidE2ERuntimeError(
                f"{RUNTIME_ENV_VAR} must be {RUNTIME_COMPOSE!r} or {RUNTIME_LAB!r}, got {explicit!r}",
            )
        return explicit

    if os.environ.get("GITHUB_ACTIONS", "").lower() in ("1", "true", "yes"):
        return RUNTIME_COMPOSE

    return job_default


def runtime_resolution_source(job_default: str) -> str:
    """Describe how :func:`active_e2e_runtime` chose the runtime (for logs)."""
    if os.environ.get(RUNTIME_ENV_VAR, "").strip():
        return RUNTIME_ENV_VAR
    if os.environ.get("GITHUB_ACTIONS", "").lower() in ("1", "true", "yes"):
        return "GITHUB_ACTIONS"
    return "job_default"


def runtime_for_testbed(testbed_path: str) -> str:
    """Return ``compose`` or ``lab`` from a testbed file path."""
    normalized = testbed_path.replace("\\", "/").rstrip("/")
    if normalized.endswith("compose.yaml"):
        return RUNTIME_COMPOSE
    if normalized.endswith("lab.yaml"):
        return RUNTIME_LAB
    return "unknown"


def runtime_for_testbed_object(testbed: Any) -> str:
    """Return ``compose`` or ``lab`` from a loaded pyATS Testbed."""
    if testbed is None:
        return "unknown"
    name = getattr(testbed, "name", "") or ""
    if name == TESTBED_NAME_COMPOSE:
        return RUNTIME_COMPOSE
    if name == TESTBED_NAME_LAB:
        return RUNTIME_LAB
    return "unknown"


def _load_testbed_yaml(relpath: str) -> Any:
    path = get_testbed_file(default=relpath)
    if not path or not os.path.isfile(path):
        return None
    from pyats import topology

    return topology.loader.load(path)


def resolve_job_testbed(easypy_runtime: Any, job_default_runtime: str) -> tuple[Any, str, str]:
    """Resolve the Testbed object and runtime label for this job.

    Returns ``(testbed, runtime, source)`` where *source* is one of
    ``cli``, ``MYCELIUM_E2E_RUNTIME``, ``GITHUB_ACTIONS``, or ``job_default``.
    """
    if easypy_runtime is not None and getattr(easypy_runtime, "testbed", None) is not None:
        testbed = easypy_runtime.testbed
        return testbed, runtime_for_testbed_object(testbed), "cli"

    runtime = active_e2e_runtime(job_default_runtime)
    source = runtime_resolution_source(job_default_runtime)
    testbed = _load_testbed_yaml(testbed_path_for_runtime(runtime))
    return testbed, runtime, source


def prepare_job_testbed(
    easypy_runtime: Any,
    logger: logging.Logger,
    *,
    job_default_runtime: str,
    allowed_runtimes: frozenset[str],
) -> tuple[Any, str, str]:
    """Resolve testbed + runtime and enforce the job's permitted runtimes."""
    testbed, runtime, source = resolve_job_testbed(easypy_runtime, job_default_runtime)

    if runtime not in allowed_runtimes:
        allowed = ", ".join(sorted(allowed_runtimes))
        raise JobRuntimeMismatchError(
            f"runtime {runtime!r} (from {source}) is not allowed for this job; "
            f"permitted: {allowed}",
        )

    actual = runtime_for_testbed_object(testbed)
    if testbed is not None and actual != "unknown" and actual != runtime:
        tb_name = getattr(testbed, "name", testbed)
        logger.warning(
            "runtime %r but testbed %r resolves to %r",
            runtime,
            tb_name,
            actual,
        )

    logger.info("Runtime active:  %s (source: %s)", runtime, source)
    return testbed, runtime, source


def validate_job_runtime(
    logger: logging.Logger,
    *,
    expected_runtime: str,
    testbed: Any,
    strict: bool = False,
) -> str:
    """Compare loaded testbed to a single expected runtime; warn or raise.

    Prefer :func:`prepare_job_testbed` with ``allowed_runtimes`` for new code.
    """
    actual = runtime_for_testbed_object(testbed)
    if actual == "unknown":
        logger.warning("Could not infer runtime from testbed %r", testbed)
        return actual
    if actual == expected_runtime:
        return actual

    tb_name = getattr(testbed, "name", testbed)
    msg = (
        f"job expects runtime {expected_runtime!r} but active testbed "
        f"{tb_name!r} is {actual!r}"
    )
    if strict:
        raise JobRuntimeMismatchError(msg)
    logger.warning("%s — continuing (CLI/env testbed override)", msg)
    return actual


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


def log_job_context(
    logger: logging.Logger,
    *,
    title: str,
    runtime: str,
    default_testbed: str | None = None,
    active_testbed: Any = None,
    tiers: str | None = None,
    suite: str | None = None,
    datafile: str | None = None,
    max_failures: int | None = None,
) -> None:
    """Emit a consistent job banner (runtime is owned by the job file)."""
    logger.info("=== %s ===", title)
    logger.info("Runtime (job):   %s", runtime)
    env_runtime = os.environ.get(RUNTIME_ENV_VAR)
    if env_runtime:
        logger.info("%s:       %s", RUNTIME_ENV_VAR, env_runtime)
    if active_testbed is not None:
        tb_name = getattr(active_testbed, "name", active_testbed)
        logger.info("Testbed active:  %s (%s)", tb_name, runtime_for_testbed_object(active_testbed))
    if tiers is not None:
        logger.info("Active tiers:    %s", tiers)
    if suite is not None:
        logger.info("Suite:           %s", suite)
    if datafile is not None:
        logger.info("Datafile:        %s", datafile)
    if default_testbed is not None:
        resolved = get_testbed_file(default=default_testbed)
        logger.info("Testbed default: %s", default_testbed)
        if resolved:
            logger.info("Testbed path:    %s", resolved)
        env_tb = os.environ.get("MYCELIUM_TESTBED_FILE")
        if env_tb:
            logger.info("Testbed (env):   %s", env_tb)
        if active_testbed is None:
            logger.info(
                "Testbed (cli):   optional override — pyats run job … --testbed-file %s",
                default_testbed,
            )
    if max_failures is not None:
        logger.info("Max failures:    %s", max_failures or "unlimited")


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


def groups_filter_from_env() -> Or | None:
    """Build a pyATS ``groups`` filter from ``MYCELIUM_E2E_GROUPS``.

    Comma-separated names are OR'd together::

        MYCELIUM_E2E_GROUPS=openclaw          → Or('openclaw')
        MYCELIUM_E2E_GROUPS=openclaw,cursor   → Or('openclaw', 'cursor')

    ``easypy.run(groups=…)`` requires a logic object (not a string).
    For ad-hoc CLI runs use ``--groups "Or('openclaw')"`` instead.
    """
    raw = os.environ.get("MYCELIUM_E2E_GROUPS", "").strip()
    if not raw:
        return None
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return None
    return Or(*names)


# Back-compat alias for callers/tests written during the string-return bug.
groups_logic_from_env = groups_filter_from_env


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
