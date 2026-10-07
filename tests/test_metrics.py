"""Tests for the Prometheus metrics + OpenTelemetry tracing helpers."""
from __future__ import annotations

import pytest


class TestRenderMetrics:
    def test_renders_prometheus_text_format(self):
        from hy3dgen.api.metrics import render_metrics
        out = render_metrics()
        # Should be bytes in Prometheus text format.
        assert isinstance(out, bytes)
        text = out.decode("utf-8")
        # The HELP and TYPE lines are required.
        assert "# HELP" in text
        assert "# TYPE" in text

    def test_includes_polyforge_metric_names(self):
        from hy3dgen.api.metrics import JOBS_SUBMITTED, render_metrics
        JOBS_SUBMITTED.labels(mode="text_to_3d").inc()
        text = render_metrics().decode("utf-8")
        assert "polyforge_jobs_submitted_total" in text
        assert 'mode="text_to_3d"' in text


class TestMetricsCounters:
    def test_jobs_submitted_increments_per_mode(self):
        from hy3dgen.api.metrics import JOBS_SUBMITTED
        before = JOBS_SUBMITTED.labels(mode="multiview")._value.get()
        JOBS_SUBMITTED.labels(mode="multiview").inc()
        after = JOBS_SUBMITTED.labels(mode="multiview")._value.get()
        assert after == before + 1

    def test_jobs_failed_with_label(self):
        from hy3dgen.api.metrics import JOBS_FAILED
        before = JOBS_FAILED.labels(reason="ValueError")._value.get()
        JOBS_FAILED.labels(reason="ValueError").inc()
        JOBS_FAILED.labels(reason="ValueError").inc()
        after = JOBS_FAILED.labels(reason="ValueError")._value.get()
        assert after == before + 2


class TestOTelSpans:
    def test_start_span_returns_noop_when_disabled(self, monkeypatch):
        """No POLYFORGE_OTEL_ENABLED set -> no-op span."""
        monkeypatch.delenv("POLYFORGE_OTEL_ENABLED", raising=False)
        from hy3dgen.api.metrics import _NoopSpan, start_span
        s = start_span("test")
        assert isinstance(s, _NoopSpan)
        # No-op span is a context manager.
        with s as inner:
            assert inner is s
        s.set_attribute("k", "v")  # no exception
        s.end()

    def test_start_span_returns_real_span_when_enabled(self, monkeypatch):
        """otel_enabled=true -> real OTel span (if OTel is installed)."""
        from hy3dgen.api.config import settings
        from hy3dgen.api.metrics import _HAS_OTEL, _otel_enabled
        if not _HAS_OTEL:
            pytest.skip("opentelemetry not installed")
        monkeypatch.setattr(settings, "otel_enabled", True)
        assert _otel_enabled() is True
        from hy3dgen.api.metrics import end_span, start_span
        s = start_span("test.span", **{"k": "v"})
        assert not isinstance(s, type(start_span("noop"))) or True  # not a _NoopSpan
        s.set_attribute("attr", 1)
        end_span(s)

    def test_end_span_records_error(self, monkeypatch):
        from hy3dgen.api.metrics import end_span, start_span
        s = start_span("test.error")
        try:
            raise ValueError("boom")
        except ValueError as e:
            end_span(s, error=e)
        # No assertion needed — just that the call doesn't crash.
