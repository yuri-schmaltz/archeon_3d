"""
Tests for the PolyForge API server (hy3dgen.api.server + hy3dgen.api.manager).

The previous version of this file defined a *parallel* ``JobManager`` class
inline and never tested the real ``PriorityRequestManager``. That meant the
suite was effectively a no-op against production code. These tests exercise
the real classes (with ``ModelWorker`` mocked out so they don't need a GPU).
"""
import asyncio
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

try:
    import torch  # noqa: F401  # PriorityRequestManager imports torch at module level
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.schemas import (
        ImageTo3DRequest,
        JobStatus,
        TextTo3DRequest,
    )
    _SKIP_REASON = None
except ModuleNotFoundError as exc:  # torch / fastapi not installed (e.g. in a CI env without GPU deps)
    PriorityRequestManager = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    TextTo3DRequest = None  # type: ignore[assignment]
    ImageTo3DRequest = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch/fastapi not installed",
)


def _run(coro):
    """Helper to run a coroutine in a fresh event loop inside a test."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# PriorityRequestManager — queue + state machine
# ---------------------------------------------------------------------------

class TestPriorityRequestManager:
    def _make_manager(self):
        # Lazy worker init: don't actually load any model.
        mgr = PriorityRequestManager(device="cpu", max_concurrent=1)
        mgr.worker = MagicMock()
        mgr.worker.generate = MagicMock(return_value="/tmp/fake.glb")
        return mgr

    async def test_init_has_empty_state(self):
        mgr = PriorityRequestManager(device="cpu")
        assert mgr.jobs == {}
        assert mgr.queue.empty()
        assert mgr._worker_task is None
        assert mgr.worker is None  # lazy

    async def test_submit_job_creates_entry_and_returns_uid(self):
        mgr = self._make_manager()
        req = TextTo3DRequest(prompt="a cat")
        uid = await mgr.submit_job(req, save_dir="/tmp")
        assert isinstance(uid, str) and len(uid) == 36
        assert uid in mgr.jobs
        assert mgr.jobs[uid].status == JobStatus.QUEUED

    async def test_get_job_returns_none_for_unknown(self):
        mgr = self._make_manager()
        assert mgr.get_job("nonexistent") is None

    async def test_cancel_queued_job(self):
        mgr = self._make_manager()
        req = TextTo3DRequest(prompt="a cat")
        uid = await mgr.submit_job(req, save_dir="/tmp")
        await mgr.cancel_job(uid)
        assert mgr.jobs[uid].status == JobStatus.CANCELLED
        assert mgr.jobs[uid].error is not None

    async def test_cancel_processing_job_is_a_noop(self):
        """A job already in PROCCESSING state cannot be cancelled (today)."""
        mgr = self._make_manager()
        req = TextTo3DRequest(prompt="a cat")
        uid = await mgr.submit_job(req, save_dir="/tmp")
        mgr.jobs[uid].status = JobStatus.PROCESSING
        await mgr.cancel_job(uid)
        # Status remains PROCESSING (cannot be cancelled mid-flight).
        assert mgr.jobs[uid].status == JobStatus.PROCESSING

    async def test_process_queue_executes_job_and_marks_completed(self):
        mgr = self._make_manager()
        req = TextTo3DRequest(prompt="a cat")

        async def _scenario():
            await mgr.start()
            uid = await mgr.submit_job(req, save_dir="/tmp")
            # Wait for the worker to process the single queued job.
            for _ in range(300):
                if mgr.jobs[uid].status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break
                await asyncio.sleep(0.1)
            await mgr.stop()
            return uid

        uid = await _scenario()
        assert mgr.jobs[uid].status == JobStatus.COMPLETED
        assert mgr.jobs[uid].file_path == "/tmp/fake.glb"
        assert mgr.jobs[uid].completed_at is not None
        mgr.worker.generate.assert_called_once()

    async def test_process_queue_marks_failed_on_exception(self):
        mgr = self._make_manager()
        mgr.worker.generate = MagicMock(side_effect=RuntimeError("GPU OOM"))
        req = TextTo3DRequest(prompt="a cat")

        async def _scenario():
            await mgr.start()
            uid = await mgr.submit_job(req, save_dir="/tmp")
            for _ in range(300):
                if mgr.jobs[uid].status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break
                await asyncio.sleep(0.1)
            await mgr.stop()
            return uid

        uid = await _scenario()
        assert mgr.jobs[uid].status == JobStatus.FAILED
        assert "GPU OOM" in (mgr.jobs[uid].error or "")

    async def test_priority_queue_orders_lower_first(self):
        """asyncio.PriorityQueue returns lower priority number first."""
        mgr = self._make_manager()
        low = await mgr.submit_job(TextTo3DRequest(prompt="low"), save_dir="/tmp", priority=1)
        high = await mgr.submit_job(TextTo3DRequest(prompt="high"), save_dir="/tmp", priority=10)
        # The order in which they were *queued* doesn't matter — priority decides execution.
        first, _, _, _, _ = mgr.queue._queue[0]
        assert first == 1  # lower priority value = higher priority


# ---------------------------------------------------------------------------
# Lazy worker init
# ---------------------------------------------------------------------------

class TestLazyWorkerInit:
    async def test_worker_is_none_before_any_job(self):
        mgr = PriorityRequestManager(device="cpu")
        # No jobs have been submitted, so the worker has not been initialized.
        assert mgr.worker is None

    async def test_worker_init_runs_on_first_job(self):
        # The manager calls ModelWorker in a thread; we patch it out so the
        # test is fast and doesn't require a GPU.
        mgr = PriorityRequestManager(device="cpu")
        fake_worker = MagicMock(generate=MagicMock(return_value="/tmp/x.glb"))

        async def _scenario():
            await mgr.start()
            with patch("hy3dgen.api.manager.ModelWorker", return_value=fake_worker):
                uid = await mgr.submit_job(TextTo3DRequest(prompt="x"), save_dir="/tmp")
                # Wait briefly for the worker task to initialize ModelWorker.
                for _ in range(50):
                    if mgr.worker is not None:
                        break
                    await asyncio.sleep(0.05)
            await mgr.stop()
            return uid

        await _scenario()
        assert mgr.worker is not None


# ---------------------------------------------------------------------------
# Server / app smoke
# ---------------------------------------------------------------------------

class TestServerApp:
    async def test_app_imports(self):
        from hy3dgen.api.server import app
        assert app.title == "PolyForge Backend"

    async def test_health_endpoint_registered(self):
        from hy3dgen.api.server import app
        # FastAPI's app.openapi() aggregates every registered route across
        # all included routers, so we can assert on the union.
        paths = set(app.openapi().get("paths", {}).keys())
        assert "/health" in paths
        assert "/v1/jobs" in paths
        assert "/v1/system/metrics" in paths
        assert "/v1/meshops/process" in paths

    async def test_main_function_exists(self):
        """The console script ``hy3dgen-api`` declared in setup.py needs a real main()."""
        from hy3dgen.api import server
        assert callable(getattr(server, "main", None))
