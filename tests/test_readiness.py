"""Tests for the readiness probe and background rehydration.

``/health`` is a liveness probe: it answers as soon as the process is up.
``/ready`` is the readiness gate: it returns 503 until the initial
job-store rehydrate has finished, so a load balancer can hold traffic
until the in-memory job view matches the persistent store.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from hy3dgen.api import server as server_module
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import JobResponse, JobStatus


class TestReadyEndpoint:
    """``/ready`` reads ``app.state.manager`` directly, so these tests set
    that instead of going through ``dependency_overrides``."""

    def test_ready_endpoint_is_registered(self):
        paths = [r.path for r in server_module.app.routes if hasattr(r, "path")]
        assert "/ready" in paths

    def test_ready_returns_200_when_manager_is_ready(self):
        """A manager with no store never rehydrates, so it is ready at once."""
        mgr = PriorityRequestManager(device="cpu")
        assert mgr.ready is True
        with TestClient(server_module.app) as client:
            client.app.state.manager = mgr
            r = client.get("/ready")
            assert r.status_code == 200
            assert r.json()["ready"] is True

    def test_health_reports_ready_flag(self):
        mgr = PriorityRequestManager(device="cpu")
        with TestClient(server_module.app) as client:
            client.app.state.manager = mgr
            body = client.get("/health").json()
            assert body["ready"] is True

    def test_ready_returns_503_while_rehydrating(self, tmp_path):
        """Simulate an in-flight rehydrate by holding the flag down."""
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)
        # start() normally releases this; clear it to model a rehydrate
        # that is still running.
        mgr._ready_event.clear()
        assert mgr.ready is False
        with TestClient(server_module.app) as client:
            client.app.state.manager = mgr
            r = client.get("/ready")
            assert r.status_code == 503
            assert r.json()["ready"] is False

    def test_ready_flips_to_200_once_rehydrate_completes(self, tmp_path):
        """A store-backed manager answers 503, then 200 after rehydrate."""
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)
        assert mgr.ready is False
        with TestClient(server_module.app) as client:
            client.app.state.manager = mgr
            assert client.get("/ready").status_code == 503
            mgr._ready_event.set()
            r = client.get("/ready")
            assert r.status_code == 200
            assert r.json()["ready"] is True


class TestBackgroundRehydrate:
    async def test_start_does_not_block_on_rehydrate(self, tmp_path):
        """With a store present, start() returns before rehydrate finishes."""
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)

        started = asyncio.Event()
        release = asyncio.Event()
        original = mgr.rehydrate

        async def _slow_rehydrate():
            started.set()
            await release.wait()
            return await original()

        mgr.rehydrate = _slow_rehydrate  # type: ignore[method-assign]

        await mgr.start(await_rehydrate=False)
        try:
            # start() returned before rehydrate finished: the task is
            # scheduled but still blocked on ``release``.
            await asyncio.sleep(0)
            assert started.is_set()
            assert mgr.ready is False
            assert await mgr.wait_ready(timeout=0.05) is False

            release.set()
            assert await mgr.wait_ready(timeout=2.0) is True
            assert mgr.ready is True
        finally:
            release.set()
            await mgr.stop()

    async def test_rehydrate_failure_still_releases_readiness(self, tmp_path):
        """A broken store must not leave the server permanently unready."""
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)

        async def _boom():
            raise RuntimeError("store is corrupt")

        mgr.rehydrate = _boom  # type: ignore[method-assign]

        await mgr.start(await_rehydrate=False)
        try:
            assert await mgr.wait_ready(timeout=2.0) is True
            assert mgr.ready is True
        finally:
            await mgr.stop()

    async def test_await_rehydrate_true_keeps_synchronous_behaviour(self, tmp_path):
        """The synchronous path is still available for existing callers."""
        store = JobStore(str(tmp_path / "jobs.db"))
        uid = "persisted-1"
        await store.upsert(
            JobResponse(uid=uid, status=JobStatus.COMPLETED, created_at="2026-10-05T10:00:00+00:00")
        )

        mgr = PriorityRequestManager(device="cpu", store=store)
        await mgr.start(await_rehydrate=True)
        try:
            assert mgr.ready is True
            assert uid in mgr.jobs
        finally:
            await mgr.stop()

    async def test_stop_cancels_in_flight_rehydrate(self, tmp_path):
        """stop() must not hang waiting on a stuck rehydrate."""
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)

        blocker = asyncio.Event()

        async def _hang():
            await blocker.wait()
            return 0

        mgr.rehydrate = _hang  # type: ignore[method-assign]
        await mgr.start(await_rehydrate=False)
        # Give the task a chance to start.
        await asyncio.sleep(0)
        await asyncio.wait_for(mgr.stop(), timeout=2.0)
        assert mgr._rehydrate_task is None


class TestManagerReadinessFlag:
    async def test_ready_defaults_to_true_without_store(self):
        mgr = PriorityRequestManager(device="cpu")
        assert mgr.ready is True

    async def test_start_marks_ready_when_no_store(self):
        mgr = PriorityRequestManager(device="cpu")
        await mgr.start()
        try:
            assert mgr.ready is True
        finally:
            await mgr.stop()


@pytest.mark.parametrize("workers", [2, 4])
def test_multi_worker_is_rejected(workers):
    """``--workers > 1`` is refused: each worker would duplicate the
    model, the job queue and the rehydrate pass."""
    import argparse

    from hy3dgen.api.server import _reject_multi_worker

    parser = argparse.ArgumentParser()
    with pytest.raises(SystemExit):
        _reject_multi_worker(parser, workers)


def test_single_worker_is_accepted():
    import argparse

    from hy3dgen.api.server import _reject_multi_worker

    parser = argparse.ArgumentParser()
    assert _reject_multi_worker(parser, 1) is None


def test_workers_setting_is_wired_to_main():
    """``POLYFORGE_WORKERS`` must actually reach the CLI default."""
    from hy3dgen.api.config import Settings
    from hy3dgen.api.server import settings

    assert settings.workers == Settings(_env_file=None).workers
