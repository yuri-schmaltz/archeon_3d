"""Tests for the list-level SSE plumbing.

Covers:
- ``PriorityRequestManager.subscribe_list`` / ``unsubscribe_list``
- ``_notify_list`` fan-out to all list subscribers
- eviction notifying list subscribers
"""
from __future__ import annotations

import asyncio
import tempfile
import os

from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import JobStatus, JobResponse


def _new_manager() -> PriorityRequestManager:
    """Build a manager with an in-memory store and no real worker."""
    tmp = tempfile.mkdtemp()
    store = JobStore(db_path=os.path.join(tmp, "t.db"))
    m = PriorityRequestManager(
        device="cpu",
        max_concurrent=1,
        max_history=100,
        store=store,
    )
    # The unit tests below don't run the worker loop; we set a dummy
    # job dict directly to simulate transitions.
    return m


def _seed_job(m: PriorityRequestManager, uid: str, status: JobStatus) -> None:
    m.jobs[uid] = JobResponse(
        uid=uid,
        status=status,
        created_at="2025-01-01T00:00:00",
    )


class TestSubscribeList:
    async def test_subscribe_list_primes_with_current_jobs(self):
        m = _new_manager()
        _seed_job(m, "a", JobStatus.QUEUED)
        _seed_job(m, "b", JobStatus.COMPLETED)
        q = m.subscribe_list()
        first = q.get_nowait()
        uids = [j.uid for j in first]
        assert uids == ["a", "b"]  # both jobs are in the snapshot
        m.unsubscribe_list(q)

    async def test_notify_list_fans_out_to_all_subscribers(self):
        m = _new_manager()
        q1 = m.subscribe_list()
        q1.get_nowait()  # drain priming
        q2 = m.subscribe_list()
        q2.get_nowait()
        _seed_job(m, "x", JobStatus.QUEUED)
        m._notify_list()  # private API but acceptable for unit testing
        snap1 = q1.get_nowait()
        snap2 = q2.get_nowait()
        assert any(j.uid == "x" for j in snap1)
        assert any(j.uid == "x" for j in snap2)
        m.unsubscribe_list(q1)
        m.unsubscribe_list(q2)

    async def test_slow_list_subscriber_receives_latest_snapshot_only(self):
        m = _new_manager()
        q = m.subscribe_list()
        q.get_nowait()
        _seed_job(m, "x", JobStatus.QUEUED)
        m._notify_list()
        m.jobs["x"].status = JobStatus.PROCESSING
        m._notify_list()
        m.jobs["x"].status = JobStatus.COMPLETED
        m._notify_list()

        assert q.qsize() == 1
        assert q.get_nowait()[0].status == JobStatus.COMPLETED
        m.unsubscribe_list(q)

    async def test_notify_via_job_transition_reaches_list_subscribers(self):
        m = _new_manager()
        q = m.subscribe_list()
        q.get_nowait()
        # Simulate a status transition: seed the job, then notify.
        _seed_job(m, "y", JobStatus.QUEUED)
        m._notify(m.jobs["y"])
        snap = q.get_nowait()
        assert any(j.uid == "y" for j in snap)
        m.unsubscribe_list(q)

    async def test_unsubscribe_list_stops_events(self):
        m = _new_manager()
        q = m.subscribe_list()
        q.get_nowait()
        m.unsubscribe_list(q)
        # Drain any subsequent event from the queue (should be empty).
        _seed_job(m, "z", JobStatus.QUEUED)
        m._notify(m.jobs["z"])
        # Confirm no event arrived within a small window.
        try:
            await asyncio.wait_for(q.get(), timeout=0.05)
            raise AssertionError("expected no event after unsubscribe")
        except asyncio.TimeoutError:
            pass  # good — no event arrived


class TestListNotifyOnEvict:
    async def test_evict_old_jobs_notifies_list_subscribers(self):
        m = _new_manager()
        m.max_history = 0  # disable size-based eviction path
        _seed_job(m, "old", JobStatus.COMPLETED)
        # Manually backdate the created_at so it qualifies as old.
        m.jobs["old"].created_at = "1990-01-01T00:00:00"
        q = m.subscribe_list()
        q.get_nowait()  # priming
        await m.evict_old_jobs(max_age_seconds=60)
        # After eviction the next event should be a fresh snapshot
        # that no longer contains "old".
        snap = q.get_nowait()
        assert all(j.uid != "old" for j in snap)
        m.unsubscribe_list(q)
