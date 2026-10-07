"""Tests for the /v1/admin/stats endpoint."""
import os
import tempfile
from datetime import datetime

import pytest

try:
    import torch  # noqa: F401
    from fastapi.testclient import TestClient
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.persistence import JobStore
    from hy3dgen.api import server as server_module
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP = None
except ModuleNotFoundError as e:
    TestClient = None  # type: ignore[assignment]
    PriorityRequestManager = None  # type: ignore[assignment]
    JobStore = None  # type: ignore[assignment]
    server_module = None  # type: ignore[assignment]
    JobResponse = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    _SKIP = str(e)


pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "deps missing")


def _make_job(uid, status, created_at="2025-01-01T00:00:00"):
    return JobResponse(uid=uid, status=status, created_at=created_at)


class TestAdminStats:
    async def test_stats_with_empty_persistence(self, monkeypatch, tmp_path):
        """Endpoint reports zero counts when the store is empty."""
        db = tmp_path / "jobs.db"
        monkeypatch.setenv("POLYFORGE_JOB_DB", str(db))
        # Reload settings to pick up the new env var
        import importlib
        from hy3dgen.api import config as cfg_mod
        importlib.reload(cfg_mod)
        from hy3dgen.api import server as sm
        importlib.reload(sm)
        with TestClient(sm.app) as client:
            r = client.get("/v1/admin/stats")
            assert r.status_code == 200
            data = r.json()
            assert data["queue_depth"] == 0
            assert data["jobs_in_memory"] == 0
            assert data["jobs_in_store"] == 0
            assert data["by_status"] == {}
            assert data["persistence_enabled"] is True
            assert data["max_history"] > 0

    async def test_stats_counts_by_status(self, monkeypatch, tmp_path):
        """Endpoint counts jobs in memory grouped by status."""
        # Pre-populate the in-memory state by writing through a JobStore
        # that the lifespan will pick up on rehydrate.
        db = tmp_path / "jobs.db"
        monkeypatch.setenv("POLYFORGE_JOB_DB", str(db))
        import importlib
        from hy3dgen.api import config as cfg_mod
        importlib.reload(cfg_mod)
        from hy3dgen.api import server as sm
        importlib.reload(sm)

        # The lifespan creates the manager from scratch. We need to
        # inject jobs AFTER the lifespan runs but BEFORE we hit the
        # endpoint. The cleanest way: use the same app, but override
        # ``app.state.manager`` with our pre-populated one.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def seed_lifespan(app):
            # Run the real lifespan first (creates manager + store)
            async with sm.lifespan(app):
                # Then augment the manager with our jobs.
                app.state.manager.jobs["a"] = _make_job("a", JobStatus.QUEUED)
                app.state.manager.jobs["b"] = _make_job("b", JobStatus.QUEUED)
                app.state.manager.jobs["c"] = _make_job("c", JobStatus.COMPLETED)
                yield

        sm.app.router.lifespan_context = seed_lifespan
        with TestClient(sm.app) as client:
            r = client.get("/v1/admin/stats")
            data = r.json()
            assert data["jobs_in_memory"] == 3
            assert data["by_status"]["queued"] == 2
            assert data["by_status"]["completed"] == 1
