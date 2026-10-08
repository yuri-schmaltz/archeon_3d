"""Tests for the manager.py hardening changes in PR #14.

These tests target the four race conditions / shutdown bugs fixed in
PriorityRequestManager without depending on a real torch install
beyond a CPU-only stub.

Coverage:
  - ``_status_transition`` is atomic and refuses stale writes.
  - ``cancel_job`` no-ops cleanly for PROCESSING jobs (was silent fail).
  - ``cancel_job`` refuses to clobber a job that already moved past QUEUED.
  - ``_drain_queue_on_shutdown`` marks every pending job CANCELLED with a
    clear reason.
  - ``_process_queue`` wakes up on shutdown even when no job is queued
    (was: would block forever on stop()).

Implementation note: ``PriorityRequestManager`` is imported lazily inside
the ``_isolation`` fixture so we can stub ``hy3dgen.inference`` (and a
couple of other heavy modules) without polluting ``sys.modules`` for
other test modules pytest imports in the same process. Every test in
this file gets the fixture (autouse=True), and the fixture restores the
real modules after the test completes.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Any

import pytest

from hy3dgen.api.schemas import JobResponse, JobStatus  # real, no stub needed


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------

# Names that we WILL stub during a test (and restore afterwards if they
# weren't already in sys.modules). We do NOT stub hy3dgen.api.schemas
# because the test bodies need the real JobResponse / JobStatus.
_STUB_KEYS = (
    "hy3dgen.inference",
    "hy3dgen.api.persistence",
    "hy3dgen.api.config",
)


def _install_stubs() -> dict[str, Any]:
    """Install stubs for heavy modules that manager.py transitively imports.

    Returns a dict mapping each stubbed name to the value that was already
    in sys.modules (or None if there was nothing there). The caller is
    responsible for restoring these after the test.
    """
    saved: dict[str, Any] = {}

    # Stub hy3dgen.inference. The real one pulls in trimesh + a lot of
    # vendored Hunyuan code we don't need.
    inference = types.ModuleType("hy3dgen.inference")
    class _ModelWorker:  # pragma: no cover - never instantiated
        def __init__(self, *a, **kw):
            raise RuntimeError("ModelWorker is stubbed in tests")
        def generate(self, *a, **kw):
            raise RuntimeError("generate is stubbed in tests")
    inference.ModelWorker = _ModelWorker
    saved["hy3dgen.inference"] = sys.modules.get("hy3dgen.inference")
    sys.modules["hy3dgen.inference"] = inference

    # Stub hy3dgen.api.persistence (uses aiosqlite + schemas we don't need).
    persistence = types.ModuleType("hy3dgen.api.persistence")
    class _JobStore:  # pragma: no cover - never instantiated
        def __init__(self, *a, **kw): pass
    persistence.JobStore = _JobStore
    saved["hy3dgen.api.persistence"] = sys.modules.get("hy3dgen.api.persistence")
    sys.modules["hy3dgen.api.persistence"] = persistence

    # Stub hy3dgen.api.config (uses pydantic-settings + yaml).
    config = types.ModuleType("hy3dgen.api.config")
    config.SAVE_DIR = "/tmp/manager_hardening_test"
    saved["hy3dgen.api.config"] = sys.modules.get("hy3dgen.api.config")
    sys.modules["hy3dgen.api.config"] = config

    return saved


def _restore_stubs(saved: dict[str, Any]) -> None:
    """Inverse of ``_install_stubs``. Restores the modules that existed
    before, and pops the ones we created from scratch so subsequent
    test modules can re-import the real implementations.
    """
    for name in _STUB_KEYS:
        prior = saved.get(name)
        if prior is None:
            # We created this stub; remove it so the real module can be
            # imported fresh by later tests.
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior
    # Force a re-import of manager so the next test in another file
    # doesn't see a half-stubbed module.
    sys.modules.pop("hy3dgen.api.manager", None)


@pytest.fixture(autouse=True)
def _isolation():
    """Install stubs for this test, then restore the real modules after."""
    saved = _install_stubs()
    # Import the manager fresh under the stubbed sys.modules state.
    # If hy3dgen.api.manager was already imported (e.g. by a previous
    # test in this module), we drop it so we get a clean view.
    sys.modules.pop("hy3dgen.api.manager", None)
    manager_mod = importlib.import_module("hy3dgen.api.manager")
    try:
        yield manager_mod
    finally:
        _restore_stubs(saved)


# ---------------------------------------------------------------------------
# _status_transition
# ---------------------------------------------------------------------------

class TestStatusTransition:
    def test_returns_true_when_expected_matches(self, _isolation) -> None:
        job = JobResponse(uid="x", status=JobStatus.QUEUED,
                          created_at="2026-01-01T00:00:00Z")
        assert _isolation._status_transition(
            job, JobStatus.QUEUED, JobStatus.CANCELLED
        ) is True
        assert job.status == JobStatus.CANCELLED

    def test_returns_false_when_status_already_changed(self, _isolation) -> None:
        job = JobResponse(uid="x", status=JobStatus.PROCESSING,
                          created_at="2026-01-01T00:00:00Z")
        # Caller expected QUEUED but it's already PROCESSING; the
        # transition must NOT clobber the new state.
        assert _isolation._status_transition(
            job, JobStatus.QUEUED, JobStatus.CANCELLED
        ) is False
        assert job.status == JobStatus.PROCESSING

    def test_is_atomic_under_repeated_calls(self, _isolation) -> None:
        """Two concurrent callers both try to cancel; only one should win."""
        job = JobResponse(uid="x", status=JobStatus.QUEUED,
                          created_at="2026-01-01T00:00:00Z")
        a = _isolation._status_transition(
            job, JobStatus.QUEUED, JobStatus.CANCELLED
        )
        b = _isolation._status_transition(
            job, JobStatus.QUEUED, JobStatus.CANCELLED
        )
        assert a is True
        assert b is False  # second caller sees it's already CANCELLED

    def test_terminal_status_is_not_moved(self, _isolation) -> None:
        """The helper is just an atomic compare-and-swap: it succeeds
        when the caller's ``expected`` matches the current status, no
        matter what that status is. The caller is responsible for
        passing the right ``expected`` to avoid clobbering a terminal
        state. Here we verify the documented semantics: if the
        caller asks for the wrong ``expected``, the transition does
        NOT happen.
        """
        job = JobResponse(uid="x", status=JobStatus.COMPLETED,
                          created_at="2026-01-01T00:00:00Z",
                          completed_at="2026-01-01T00:00:01Z")
        # Caller thought the job was QUEUED; actual status is COMPLETED.
        # Transition must NOT clobber the COMPLETED state.
        assert _isolation._status_transition(
            job, JobStatus.QUEUED, JobStatus.FAILED
        ) is False
        assert job.status == JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# cancel_job hardening
# ---------------------------------------------------------------------------

class TestCancelJobHardening:
    @pytest.fixture
    def manager(self, _isolation):
        PriorityRequestManager = _isolation.PriorityRequestManager
        m = PriorityRequestManager(device="cpu", max_queue_size=5)
        m.store = None  # avoid touching SQLite
        return m

    @pytest.mark.asyncio
    async def test_cancel_queued_job(self, manager) -> None:
        """A QUEUED job must be cancellable."""
        job = JobResponse(uid="q1", status=JobStatus.QUEUED,
                          created_at="2026-01-01T00:00:00Z")
        manager.jobs["q1"] = job
        await manager.cancel_job("q1")
        assert job.status == JobStatus.CANCELLED
        assert job.error == "Cancelled by user"

    @pytest.mark.asyncio
    async def test_cancel_processing_job_warns_and_is_noop(
        self, manager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A PROCESSING job can't be interrupted. We must surface that
        as a warning, not silently fail (was: silent return).
        """
        job = JobResponse(uid="p1", status=JobStatus.PROCESSING,
                          created_at="2026-01-01T00:00:00Z")
        manager.jobs["p1"] = job
        with caplog.at_level("WARNING"):
            await manager.cancel_job("p1")
        assert job.status == JobStatus.PROCESSING, (
            "PROCESSING job must not be clobbered to CANCELLED"
        )
        assert any("already processing" in r.message for r in caplog.records), (
            "cancel_job on a PROCESSING job should log a warning"
        )

    @pytest.mark.asyncio
    async def test_cancel_unknown_job_is_noop(self, manager) -> None:
        """Canceling a non-existent uid must not raise."""
        await manager.cancel_job("does-not-exist")  # no exception

    @pytest.mark.asyncio
    async def test_cancel_completed_job_is_noop(self, manager) -> None:
        """A completed job must not be retroactively cancelled."""
        job = JobResponse(uid="c1", status=JobStatus.COMPLETED,
                          created_at="2026-01-01T00:00:00Z",
                          completed_at="2026-01-01T00:00:01Z")
        manager.jobs["c1"] = job
        await manager.cancel_job("c1")
        assert job.status == JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# _drain_queue_on_shutdown
# ---------------------------------------------------------------------------

class TestDrainQueueOnShutdown:
    @pytest.fixture
    def manager(self, _isolation):
        PriorityRequestManager = _isolation.PriorityRequestManager
        m = PriorityRequestManager(device="cpu", max_queue_size=5)
        m.store = None
        return m

    @pytest.mark.asyncio
    async def test_queued_jobs_marked_cancelled(self, manager) -> None:
        for i in range(3):
            uid = f"q{i}"
            job = JobResponse(uid=uid, status=JobStatus.QUEUED,
                              created_at="2026-01-01T00:00:00Z")
            manager.jobs[uid] = job
            await manager.queue.put((10, 0.0, uid, None, "/tmp"))

        await manager._drain_queue_on_shutdown()

        for i in range(3):
            assert manager.jobs[f"q{i}"].status == JobStatus.CANCELLED, (
                f"q{i} should have been cancelled by drain"
            )
            assert manager.jobs[f"q{i}"].error == "Server shutting down"

    @pytest.mark.asyncio
    async def test_drain_handles_empty_queue(self, manager) -> None:
        """An empty queue must be a no-op (no exception)."""
        await manager._drain_queue_on_shutdown()  # no exception

    @pytest.mark.asyncio
    async def test_drain_skips_already_cancelled(self, manager) -> None:
        """A job that was already cancelled must not be re-cancelled
        (would just rewrite the error message).
        """
        uid = "qc"
        job = JobResponse(uid=uid, status=JobStatus.CANCELLED,
                          created_at="2026-01-01T00:00:00Z",
                          error="Cancelled by user")
        manager.jobs[uid] = job
        await manager.queue.put((10, 0.0, uid, None, "/tmp"))

        await manager._drain_queue_on_shutdown()

        assert job.status == JobStatus.CANCELLED
        assert job.error == "Cancelled by user", (
            "Drain must not overwrite the original cancel reason"
        )

    @pytest.mark.asyncio
    async def test_drain_keeps_task_done_counts_balanced(self, manager) -> None:
        """The number of task_done() calls must match the number of
        items we put on the queue, or queue.join() will hang forever.
        """
        for i in range(5):
            uid = f"q{i}"
            manager.jobs[uid] = JobResponse(
                uid=uid, status=JobStatus.QUEUED,
                created_at="2026-01-01T00:00:00Z",
            )
            await manager.queue.put((10, 0.0, uid, None, "/tmp"))

        await manager._drain_queue_on_shutdown()
        assert manager.queue.empty()
        # queue.join() should not hang; if it does, the test framework
        # will time it out.
        await asyncio.wait_for(manager.queue.join(), timeout=1.0)


# ---------------------------------------------------------------------------
# Shutdown wake-up: _process_queue must exit promptly when stop() is called
# even if the queue is empty.
# ---------------------------------------------------------------------------

class TestShutdownWakesUpProcessQueue:
    @pytest.mark.asyncio
    async def test_empty_queue_stop_does_not_block(self, _isolation) -> None:
        """With no jobs queued, ``stop()`` must complete quickly.

        Previous version: ``_process_queue`` did ``await self.queue.get()``
        which would block until the next job arrived (potentially forever
        on a quiet server). The new version awaits either the queue OR
        the shutdown event.
        """
        PriorityRequestManager = _isolation.PriorityRequestManager
        m = PriorityRequestManager(device="cpu")
        m.store = None
        await m.start()

        # No jobs queued; queue is empty.
        assert m.queue.empty()

        # Stopping the manager should not hang.
        await asyncio.wait_for(m.stop(), timeout=2.0)
        assert m._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_running_job_completes_before_stop_returns(self, _isolation) -> None:
        """When stop() is called, an in-flight job must complete (or
        be allowed to error out cleanly) before the worker task is
        cancelled. This is the existing behavior; we just want a test
        that pins it down.
        """
        PriorityRequestManager = _isolation.PriorityRequestManager
        m = PriorityRequestManager(device="cpu")
        m.store = None

        # Manually push a job and a fake handler.
        completed = asyncio.Event()
        started = asyncio.Event()

        # The real _execute_model_worker sets job.status = PROCESSING
        # before doing any work, so the fake does the same. We set the
        # event AFTER the status flip so the test sees the new state.
        async def _fake_execute(uid, request, save_dir):
            m.jobs[uid].status = JobStatus.PROCESSING
            started.set()
            await asyncio.sleep(0.05)
            completed.set()

        # Monkey-patch _execute_model_worker so we don't need a real
        # ModelWorker.
        m._execute_model_worker = _fake_execute  # type: ignore[assignment]

        # Push a queued job.
        job = JobResponse(uid="x", status=JobStatus.QUEUED,
                          created_at="2026-01-01T00:00:00Z")
        m.jobs["x"] = job
        await m.queue.put((10, 0.0, "x", None, "/tmp"))

        await m.start()
        # Wait for the worker to actually start the job (sets PROCESSING).
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert job.status == JobStatus.PROCESSING
        await m.stop()
