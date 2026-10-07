"""Tests for the /metrics endpoint and the rate limiter wiring."""
from __future__ import annotations

import pytest


try:
    from fastapi.testclient import TestClient
    from hy3dgen.api import server as server_module
    _SKIP = None
except ModuleNotFoundError as e:
    _SKIP = str(e)


pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "deps missing")


class TestMetricsEndpoint:
    def test_metrics_endpoint_is_registered(self):
        paths = [r.path for r in server_module.app.routes if hasattr(r, "path")]
        assert "/metrics" in paths

    def test_metrics_returns_prometheus_text(self, monkeypatch):
        """Hit /metrics on a TestClient; response should be text/plain."""
        # Configure a minimal manager stub so the lifespan succeeds.
        class _StubManager:
            queue = type("Q", (), {"qsize": staticmethod(lambda: 0)})()
            jobs: dict = {}
            worker = None
            store = None
            last_error = None
        monkeypatch.setattr(server_module, "JobStore", lambda *_a, **_k: None)

        # Replace the lifespan with a no-op so the test doesn't actually
        # touch the database.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def noop_lifespan(app):
            app.state.manager = _StubManager()
            app.state.mesh_processor = type("MP", (), {"process": staticmethod(lambda *_: "/tmp/x")})()
            yield

        monkeypatch.setattr(server_module.app, "router", server_module.app.router)
        # Use the existing lifespan as-is; it will create a real JobStore
        # (pointed at a temp path by patching get_job_db_path).
        import tempfile, os
        tmp_db = os.path.join(tempfile.mkdtemp(), "jobs.db")
        monkeypatch.setenv("POLYFORGE_JOB_DB", tmp_db)
        from hy3dgen.api.config import settings
        # Reload settings to pick up the new env var
        import importlib
        from hy3dgen.api import config as cfg_mod
        importlib.reload(cfg_mod)
        # Reload server to pick up new config
        importlib.reload(server_module)
        with TestClient(server_module.app) as client:
            r = client.get("/metrics")
            assert r.status_code == 200
            assert "text/plain" in r.headers["content-type"]
            body = r.text
            assert "polyforge_jobs_submitted_total" in body or "polyforge_jobs_in_memory" in body
