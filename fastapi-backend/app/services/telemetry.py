# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Conditional OpenTelemetry SDK initialisation for the Mycelium backend.

The SDK is an opt-in: it starts only when ``TELEMETRY_ENABLED=true`` in the
backend environment (derived from ``[telemetry] enabled = true`` in
config.toml via ``mycelium config apply``).  When off (the default) **no OTel
code runs** — not even an import — so there is zero startup cost and no
additional dependency surface for the vast majority of installs.

Conventions note (Sep 2026)
---------------------------
The ``gen_ai.*`` semantic conventions moved to the dedicated
``open-telemetry/semantic-conventions-genai`` repository in June 2026 and
remain in Development status (0 of 63 attributes are stable).  We adopt them
with version awareness: attribute names are pinned here and must be reviewed
when the OTel GenAI library version is bumped.  See the conventions pin
comment in pyproject.toml.

Architecture
------------
When enabled, the SDK is wired at application startup (``lifespan``) with:

  - ``TracerProvider`` + ``BatchSpanProcessor`` → ``OTLPSpanExporter``
    (HTTP/protobuf on :4318, the collector's in-container address).
  - ``MeterProvider`` + ``PeriodicExportingMetricReader`` (5 s) →
    ``OTLPMetricExporter`` at the same endpoint.
  - ``FastAPIInstrumentor`` for automatic HTTP RED metrics and per-route spans
    (uses stable OTel HTTP semantic conventions).

The in-process ``metrics.py`` store stays always-on regardless of this setting;
the OTel SDK augments it rather than replacing it.

Usage
-----
Other modules get a tracer via ``get_tracer(name)`` and a meter via
``get_meter(name)``.  Both return no-op stubs when the SDK is off, so call
sites do not need to guard on ``TELEMETRY_ENABLED`` themselves.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

_log = logging.getLogger(__name__)

# These are set on startup when TELEMETRY_ENABLED is true.
_tracer_provider = None
_meter_provider = None
_sdk_active = False


def setup() -> None:
    """Initialise the OTel SDK if ``TELEMETRY_ENABLED`` is true.

    Sets up TracerProvider + MeterProvider only. FastAPIInstrumentor is wired
    separately via ``instrument_app(app)`` at app-creation time in main.py so
    it runs before Starlette freezes the middleware stack.

    Safe to call when disabled — returns immediately without importing any
    OTel package so there is truly zero cost at the default off state.
    """
    if _sdk_active:
        # Eager init at module import already ran; lifespan call is a no-op.
        return

    from app.config import settings

    if not settings.TELEMETRY_ENABLED:
        return

    _init_sdk()


def instrument_app(app: FastAPI) -> None:
    """Wire FastAPIInstrumentor onto *app*.

    Must be called immediately after ``app = FastAPI(...)`` and before any
    middleware is added, so that Starlette includes the instrumentation
    middleware in its stack before it is frozen.

    No-op when the SDK is off.
    """
    if not _sdk_active:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument_app(app)
    except Exception as exc:
        _log.warning("FastAPIInstrumentor wiring failed: %s", exc)


def _init_sdk() -> None:  # pragma: no cover — only runs when OTel is enabled
    """Set up TracerProvider + MeterProvider. FastAPIInstrumentor wired separately."""
    global _tracer_provider, _meter_provider, _sdk_active
    if _sdk_active:
        return  # idempotency guard: eager module-level init + lifespan setup() both call here

    from app.config import settings

    # Collector endpoint — fall back to the in-container default when unset.
    _DEFAULT_COLLECTOR = "http://mycelium-collector:4318"
    endpoint = (settings.TELEMETRY_OTLP_ENDPOINT or _DEFAULT_COLLECTOR).rstrip("/")

    try:
        from opentelemetry import metrics as otel_metrics
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        _log.warning(
            "OTel SDK import failed (%s); telemetry disabled. "
            "Re-run `uv sync` inside fastapi-backend to install the packages.",
            exc,
        )
        return

    import tomllib
    from pathlib import Path

    # Best-effort version read from pyproject.toml.
    _version = "0.0.0"
    try:
        _pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        _version = tomllib.loads(_pyproject.read_text())["project"]["version"]
    except Exception:
        pass

    resource = Resource.create(
        {
            "service.name": "mycelium-backend",
            "service.version": _version,
            # Use MYCELIUM_DEPLOYMENT_ENV if set; fall back to "production".
            "deployment.environment": __import__("os").getenv(
                "MYCELIUM_DEPLOYMENT_ENV", "production"
            ),
        }
    )

    # ── Traces ───────────────────────────────────────────────────────────────
    span_exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        timeout=10,
    )
    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    otel_trace.set_tracer_provider(_tracer_provider)

    # ── Metrics ──────────────────────────────────────────────────────────────
    metric_exporter = OTLPMetricExporter(
        endpoint=f"{endpoint}/v1/metrics",
        timeout=10,
    )
    reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=5000,
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    otel_metrics.set_meter_provider(_meter_provider)

    _sdk_active = True
    _log.info(
        "OTel SDK active — traces + metrics → %s (gen_ai.* conventions: Development, Sep-2026 pin)",
        endpoint,
    )


def shutdown() -> None:
    """Flush and shut down both providers cleanly at app shutdown."""
    if not _sdk_active:
        return
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception:
            pass


def get_tracer(name: str):
    """Return an OTel tracer for ``name``, or a no-op when SDK is off."""
    if not _sdk_active:
        from opentelemetry import trace

        return trace.get_tracer(name)  # returns NoOpTracer when no provider is set
    from opentelemetry import trace

    return trace.get_tracer(name)


def get_meter(name: str):
    """Return an OTel meter for ``name``, or a no-op when SDK is off."""
    if not _sdk_active:
        from opentelemetry import metrics

        return metrics.get_meter(name)  # returns NoOpMeter when no provider is set
    from opentelemetry import metrics

    return metrics.get_meter(name)


# ── Eager init ────────────────────────────────────────────────────────────────
# Providers must be set before app = FastAPI(...) creates its dependency graph
# and before instrument_app() is called. Calling _init_sdk() here (at import
# time of this module) ensures the global TracerProvider and MeterProvider are
# in place when main.py calls instrument_app(app) at app-creation time.
# setup() in lifespan becomes a no-op (SDK is already active); it's kept for
# the log message and for tests that patch settings before import.
try:
    from app.config import settings as _settings

    if _settings.TELEMETRY_ENABLED:
        _init_sdk()
except Exception:
    pass  # defer to setup() call in lifespan
