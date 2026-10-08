"""
Tests for PriorityRequestManager job eviction logic.

Covers:
- ``evict_old_jobs`` keeps active jobs and drops terminal jobs past the TTL.
- ``evict_to_size`` caps the in-memory history at ``max_history``.
- Active jobs (queued, processing) are never evicted.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

try:
    import torch  # noqa: F401
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    PriorityRequestManager = None  # type: ignore[assignment]
    JobResponse = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


if JobStatus is not None:
    QUEUED, PROCESSING, COMPLETED, FAILED, CANCELLED = (
        JobStatus.QUEUED,
        JobStatus.PROCESSING,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    )
else:
    QUEUED = PROCESSING = COMPLETED = FAILED = CANCELLED = None  # type: ignore[assignment]


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch not installed",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr():
    """Fresh manager with no history cap (default)."""
    m = PriorityRequestManager(device="cpu", max_history=0)
    m.worker = MagicMock()
    m.worker.generate = MagicMock(return_value="/tmp/fake.glb")
    return m


@pytest.fixture
def small_mgr():
    """Fresh manager with max_history=5."""
    m = PriorityRequestManager(device="cpu", max_history=5)
    m.worker = MagicMock()
    m.worker.generate = MagicMock(return_value="/tmp/fake.glb")
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_terminal_job(mgr, uid, status, age_seconds):
    job = JobResponse(
        uid=uid,
        status=status,
        created_at=(datetime.utcnow() - timedelta(seconds=age_seconds)).isoformat(),
    )
    job.completed_at = datetime.utcnow().isoformat()
    mgr.jobs[uid] = job
    return job


def _add_active_job(mgr, uid, status):
    job = JobResponse(
        uid=uid,
        status=status,
        created_at=datetime.utcnow().isoformat(),
    )
    mgr.jobs[uid] = job
    return job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvictOldJobs:
    async def test_drops_old_completed(self, mgr):
        _add_terminal_job(mgr, "old-done", COMPLETED, age_seconds=10**6)
        _add_terminal_job(mgr, "recent-done", COMPLETED, age_seconds=5)
        removed = await mgr.evict_old_jobs(max_age_seconds=3600)
        assert removed == 1
        assert "old-done" not in mgr.jobs
        assert "recent-done" in mgr.jobs

    async def test_drops_old_failed_and_cancelled(self, mgr):
        _add_terminal_job(mgr, "old-fail", FAILED, age_seconds=10**6)
        _add_terminal_job(mgr, "old-cancel", CANCELLED, age_seconds=10**6)
        await mgr.evict_old_jobs(max_age_seconds=3600)
        assert "old-fail" not in mgr.jobs
        assert "old-cancel" not in mgr.jobs

    async def test_keeps_active_jobs(self, mgr):
        _add_active_job(mgr, "queued", QUEUED)
        _add_active_job(mgr, "processing", PROCESSING)
        await mgr.evict_old_jobs(max_age_seconds=3600)
        assert mgr.jobs["queued"].status == QUEUED
        assert mgr.jobs["processing"].status == PROCESSING

    async def test_invalid_iso_does_not_crash(self, mgr):
        job = JobResponse(uid="bad", status=COMPLETED, created_at="not-iso")
        mgr.jobs["bad"] = job
        assert await mgr.evict_old_jobs(max_age_seconds=3600) == 0
        assert "bad" in mgr.jobs

    async def test_returns_zero_on_empty(self, mgr):
        assert await mgr.evict_old_jobs(max_age_seconds=3600) == 0


class TestEvictToSize:
    async def test_disabled_when_max_history_zero(self, mgr):
        for i in range(50):
            _add_terminal_job(mgr, f"j{i}", COMPLETED, age_seconds=1)
        assert await mgr.evict_to_size() == 0
        assert len(mgr.jobs) == 50

    async def test_caps_to_max_history(self, small_mgr):
        # j00 is the most recent (age=10s), j09 is the oldest (age=19s).
        for i in range(10):
            _add_terminal_job(small_mgr, f"j{i:02d}", COMPLETED, age_seconds=10 + i)
        # 10 > 5 → evict the 5 oldest, keep the 5 most recent (j00..j04).
        removed = await small_mgr.evict_to_size()
        assert removed == 5
        assert len(small_mgr.jobs) == 5
        for i in range(5):
            assert f"j{i:02d}" in small_mgr.jobs
        for i in range(5, 10):
            assert f"j{i:02d}" not in small_mgr.jobs

    async def test_does_not_evict_active_jobs(self, small_mgr):
        # Make the cap even tighter to force eviction pressure.
        small_mgr.max_history = 2
        _add_active_job(small_mgr, "active", PROCESSING)
        _add_terminal_job(small_mgr, "old", COMPLETED, age_seconds=10**6)
        _add_terminal_job(small_mgr, "recent", COMPLETED, age_seconds=1)
        await small_mgr.evict_to_size()
        assert "active" in small_mgr.jobs
        assert "recent" in small_mgr.jobs
        assert "old" not in small_mgr.jobs

    async def test_under_limit_no_op(self, mgr):
        mgr.max_history = 100
        _add_terminal_job(mgr, "j1", COMPLETED, age_seconds=1)
        assert await mgr.evict_to_size() == 0
        assert len(mgr.jobs) == 1

    async def test_size_eviction_removes_artifact(self, tmp_path, monkeypatch):
        from hy3dgen.api import config

        monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
        artifact = tmp_path / "old.glb"
        artifact.write_bytes(b"old mesh")
        manager = PriorityRequestManager(device="cpu", max_history=1)
        old = JobResponse(
            uid="old",
            status=COMPLETED,
            created_at="1990-01-01T00:00:00+00:00",
            file_path=str(artifact),
        )
        manager.jobs[old.uid] = old
        manager.jobs["new"] = JobResponse(
            uid="new",
            status=COMPLETED,
            created_at="2026-10-08T00:00:00+00:00",
        )

        assert await manager.evict_to_size() == 1
        assert not artifact.exists()
        assert "old" not in manager.jobs


class TestAggressiveCleanup:
    async def test_cleanup_removes_expired_artifact_before_pruning_record(
        self, tmp_path, monkeypatch
    ):
        from hy3dgen.api import config
        from hy3dgen.api.persistence import JobStore

        monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
        artifact = tmp_path / "expired.glb"
        artifact.write_bytes(b"old mesh")
        store = JobStore(str(tmp_path / "jobs.db"))
        manager = PriorityRequestManager(
            device="cpu",
            store=store,
            max_age_seconds=1,
        )
        job = JobResponse(
            uid="expired",
            status=COMPLETED,
            created_at="1990-01-01T00:00:00+00:00",
            completed_at="1990-01-01T00:00:01+00:00",
            file_path=str(artifact),
        )
        manager.jobs[job.uid] = job
        await manager._persist(job)

        await manager._aggressive_cleanup()

        assert not artifact.exists()
        assert job.uid not in manager.jobs
        assert await store.get(job.uid) is None
