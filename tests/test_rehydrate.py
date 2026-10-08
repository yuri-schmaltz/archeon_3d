"""Tests for the manager's rehydrate path (round-trip with the store).

Covers:
- A QUEUED job with a stored payload is re-queued and reaches the
  in-memory queue with a reconstructed ``JobRequest``.
- A job without a stored payload is marked FAILED with a helpful
  error instead of silently disappearing.
- A job with a malformed stored payload is also marked FAILED.
"""
from __future__ import annotations

import asyncio
import tempfile
import os
from datetime import datetime

from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import JobRequest, JobStatus, JobResponse, TextTo3DRequest


async def _build_manager_with_active_job(payload: dict | None) -> PriorityRequestManager:
    """Spin up a manager, write a QUEUED job to the store, and stop.

    Returns the manager; the caller can call ``rehydrate()`` to drive
    the restoration.
    """
    tmp = tempfile.mkdtemp()
    store = JobStore(db_path=os.path.join(tmp, "t.db"))
    m = PriorityRequestManager(
        device="cpu",
        max_concurrent=1,
        max_history=100,
        store=store,
    )
    # Build a job in QUEUED state and persist it (with payload).
    job = JobResponse(
        uid="abc-123",
        status=JobStatus.QUEUED,
        created_at=datetime.utcnow().isoformat(),
    )
    m.jobs[job.uid] = job
    await m._persist(job, payload=payload)
    # Empty in-memory queue (the new manager has nothing in it).
    return m


class TestRehydrateWithPayload:
    async def test_rehydrated_queued_job_with_payload_is_replayed(self):
        payload = {
            "type": "text_to_3d",
            "prompt": "a small red cube",
            "guidance": 5.0,
            "steps": 50,
            "seed": 1234,
        }
        m = await _build_manager_with_active_job(payload)
        # Clear the in-memory jobs dict to simulate a fresh process.
        m.jobs.clear()
        m.queue = asyncio.PriorityQueue()  # ensure empty
        n = await m.rehydrate()
        assert n == 1
        assert "abc-123" in m.jobs
        # The job is in the queue with a non-None request.
        assert not m.queue.empty()
        priority, _ts, uid, request, save_dir = m.queue.get_nowait()
        assert priority == 100
        assert uid == "abc-123"
        # JobRequest is an Annotated Union alias, so isinstance() doesn't
        # work — check the concrete class instead.
        assert isinstance(request, TextTo3DRequest)
        assert request.prompt == "a small red cube"

    async def test_shared_service_receives_rehydrated_job(self):
        from hy3dgen.api.inference_service import InferenceService

        payload = {"type": "text_to_3d", "prompt": "resume this job"}
        previous = await _build_manager_with_active_job(payload)
        service = InferenceService(device="cpu", save_dir="/tmp")
        manager = PriorityRequestManager(
            device="cpu",
            store=previous.store,
            inference_service=service,
        )

        assert await manager.rehydrate() == 1
        assert manager.queue.empty()
        assert service._queue.qsize() == 1
        restored = service._queue.get_nowait()
        assert restored.uid == "abc-123"
        assert restored.params["type"] == "text_to_3d"
        assert restored.params["prompt"] == "resume this job"

    async def test_shared_service_replays_more_jobs_than_queue_capacity(
        self, tmp_path, monkeypatch
    ):
        from hy3dgen.api.inference_service import (
            InferenceEvent,
            InferenceService,
            JobStage,
        )

        store = JobStore(str(tmp_path / "many-jobs.db"))
        for index in range(3):
            job = JobResponse(
                uid=f"queued-{index}",
                status=JobStatus.QUEUED,
                created_at=datetime.utcnow().isoformat(),
            )
            await store.upsert(
                job,
                request_payload={"type": "text_to_3d", "prompt": f"job {index}"},
            )

        service = InferenceService(device="cpu", save_dir="/tmp", max_queue_size=1)
        executed = []

        async def fake_execute(self, job):
            executed.append(job.uid)
            self._publish(
                InferenceEvent(
                    uid=job.uid,
                    stage=JobStage.COMPLETED,
                    file_path=f"/tmp/{job.uid}.glb",
                    request_type=job.request_type,
                )
            )

        monkeypatch.setattr(InferenceService, "_execute", fake_execute)
        manager = PriorityRequestManager(
            device="cpu",
            store=store,
            max_queue_size=1,
            inference_service=service,
        )

        await manager.start(await_rehydrate=True)
        await asyncio.wait_for(service._queue.join(), timeout=2)
        for _ in range(20):
            if all(manager.jobs[uid].status == JobStatus.COMPLETED for uid in executed):
                break
            await asyncio.sleep(0.01)
        await manager.stop()

        assert set(executed) == {"queued-0", "queued-1", "queued-2"}
        assert all(manager.jobs[uid].status == JobStatus.COMPLETED for uid in executed)

    async def test_rehydrated_queued_job_without_payload_is_marked_failed(self):
        m = await _build_manager_with_active_job(None)
        m.jobs.clear()
        n = await m.rehydrate()
        assert n == 1
        job = m.jobs["abc-123"]
        assert job.status == JobStatus.FAILED
        assert "payload" in (job.error or "").lower()
        # And nothing in the queue.
        assert m.queue.empty()

    async def test_rehydrated_queued_job_with_bad_payload_is_marked_failed(self):
        # Not a valid JobRequest (missing required fields).
        m = await _build_manager_with_active_job({"type": "unknown_kind"})
        m.jobs.clear()
        await m.rehydrate()
        job = m.jobs["abc-123"]
        assert job.status == JobStatus.FAILED
        assert "deserializ" in (job.error or "").lower()
