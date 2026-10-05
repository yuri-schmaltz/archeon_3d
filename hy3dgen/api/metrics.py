"""Prometheus metrics for the Archeon API.

Counters and gauges are kept as module-level singletons so all
request paths can update them without dependency injection. The
``/metrics`` endpoint (added in ``server.py``) serialises the default
prometheus registry.

Why not ``prometheus-fastapi-instrumentator``?  It would auto-track
HTTP request metrics, but the job lifecycle (queued/processing/
completed/failed) is the interesting signal and that's easier to
track by hand.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Use the default global registry so /metrics is one-shot.
REGISTRY: CollectorRegistry | None = None  # None means "use prom default"

# -- Job lifecycle ----------------------------------------------------
JOBS_SUBMITTED = Counter(
    "archeon_jobs_submitted_total",
    "Total number of generation jobs submitted.",
    ["mode"],  # text_to_3d | image_to_3d | multiview | texture_mesh
)
JOBS_COMPLETED = Counter(
    "archeon_jobs_completed_total",
    "Total number of generation jobs that completed successfully.",
)
JOBS_FAILED = Counter(
    "archeon_jobs_failed_total",
    "Total number of generation jobs that failed (per reason).",
    ["reason"],
)
JOBS_CANCELLED = Counter(
    "archeon_jobs_cancelled_total",
    "Total number of generation jobs that were cancelled by the user.",
)
JOBS_REHYDRATED = Counter(
    "archeon_jobs_rehydrated_total",
    "Total number of jobs restored from the persistent store on startup.",
)

# -- Queue + manager state -------------------------------------------
QUEUE_DEPTH = Gauge(
    "archeon_queue_depth",
    "Current number of jobs waiting in the priority queue.",
)
JOBS_IN_MEMORY = Gauge(
    "archeon_jobs_in_memory",
    "Number of jobs currently tracked in the manager's in-memory state.",
)
JOBS_IN_STORE = Gauge(
    "archeon_jobs_in_store",
    "Number of jobs currently persisted in SQLite (0 if persistence is off).",
)
PERSISTENCE_ENABLED = Gauge(
    "archeon_persistence_enabled",
    "1 if SQLite-backed persistence is enabled, else 0.",
)
MODEL_LOADED = Gauge(
    "archeon_model_loaded",
    "1 once the inference worker has been initialised, else 0.",
)

# -- Latency ----------------------------------------------------------
JOB_DURATION = Histogram(
    "archeon_job_duration_seconds",
    "End-to-end duration of completed jobs (queue + processing).",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)


def render_metrics() -> bytes:
    """Render the metrics registry in Prometheus text format."""
    return generate_latest()


__all__ = [
    "JOBS_CANCELLED",
    "JOBS_COMPLETED",
    "JOBS_FAILED",
    "JOBS_IN_MEMORY",
    "JOBS_IN_STORE",
    "JOBS_REHYDRATED",
    "JOBS_SUBMITTED",
    "JOB_DURATION",
    "MODEL_LOADED",
    "PERSISTENCE_ENABLED",
    "QUEUE_DEPTH",
    "render_metrics",
]


# ---------------------------------------------------------------------------
# OpenTelemetry tracing (optional)
# ---------------------------------------------------------------------------
# Tracing is opt-in: if the OTel SDK is installed AND ``ARCHEON_OTEL_ENABLED=true``
# is set, spans are emitted for job lifecycle events. Otherwise the helpers
# below are no-ops, so the rest of the code can call them unconditionally.

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


def _otel_enabled() -> bool:
    """True iff OTel is installed AND the user opted in via env."""
    if not _HAS_OTEL:
        return False
    import os

    return os.environ.get("ARCHEON_OTEL_ENABLED", "").lower() in ("1", "true", "yes")


def start_span(name: str, **attrs: object):
    """Start an OTel span if enabled; otherwise return a no-op context manager.

    The return value is safe to use in a ``with`` statement regardless of
    whether OTel is installed.
    """
    if not _otel_enabled():
        return _NoopSpan()
    tracer = trace.get_tracer("hy3dgen.api")
    span = tracer.start_span(name, attributes=dict(attrs))
    return span


def end_span(span: object, *, error: BaseException | None = None) -> None:
    """Finish a span, recording any error. No-op for the placeholder."""
    if isinstance(span, _NoopSpan):
        return
    # `span` is a real OTel span at this point. We use ``cast`` because
    # the type is `object` (could be a no-op or a Span depending on env).
    from typing import cast

    real_span = cast("Any", span)
    if _HAS_OTEL and error is not None:
        real_span.set_status(Status(StatusCode.ERROR, str(error)))
        real_span.record_exception(error)
    real_span.end()


class _NoopSpan:
    """Stand-in for OTel's ``Span`` when tracing is disabled."""

    def set_attribute(self, *_args: object, **_kwargs: object) -> None: ...
    def set_status(self, *_args: object, **_kwargs: object) -> None: ...
    def record_exception(self, *_args: object, **_kwargs: object) -> None: ...
    def end(self) -> None: ...
    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *_args: object) -> None:
        return
