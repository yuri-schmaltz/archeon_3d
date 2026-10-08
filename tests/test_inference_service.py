"""Tests for the shared InferenceService."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hy3dgen.api.inference_service import (
    InferenceEvent,
    InferenceJob,
    InferenceService,
    JobStage,
)


class _StubWorker:
    """Stand-in for ``ModelWorker`` that records calls and emits a file path."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, uid: str, params: dict, save_dir: str) -> str:
        self.calls.append({"uid": uid, "params": params, "save_dir": save_dir})
        return f"{save_dir}/{uid}.glb"


@pytest.fixture
def service_with_stub(monkeypatch: pytest.MonkeyPatch) -> tuple[InferenceService, _StubWorker]:
    svc = InferenceService(device="cpu", save_dir="/tmp")
    stub = _StubWorker()

    async def fake_to_thread(func, /, *args, **kwargs):
        # In tests we don't actually need the worker instance — the stub
        # is patched in below by overriding _execute directly.
        return stub

    async def fake_execute(self: InferenceService, job: InferenceJob) -> None:
        # Replace _worker assignment + delegate to the stub.
        self._worker = stub
        self._publish(
            InferenceEvent(uid=job.uid, stage=JobStage.SHAPE_GENERATION, progress=0.4)
        )
        file_path = stub.generate(job.uid, job.params, job.save_dir)
        self._publish(
            InferenceEvent(uid=job.uid, stage=JobStage.EXPORTING, progress=0.95)
        )
        self._publish(
            InferenceEvent(
                uid=job.uid, stage=JobStage.COMPLETED, progress=1.0, file_path=file_path
            )
        )

    monkeypatch.setattr("hy3dgen.api.inference_service.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(InferenceService, "_execute", fake_execute)
    return svc, stub


@pytest.mark.asyncio
async def test_start_and_stop(service_with_stub: tuple[InferenceService, _StubWorker]) -> None:
    svc, _ = service_with_stub
    await svc.start()
    assert svc._worker_task is not None
    await svc.stop()
    assert svc._worker_task is None


@pytest.mark.asyncio
async def test_submit_publishes_queued_then_completed(
    service_with_stub: tuple[InferenceService, _StubWorker],
) -> None:
    svc, stub = service_with_stub
    await svc.start()
    queue = svc.subscribe()
    job = await svc.submit({"type": "text_to_3d", "prompt": "cube"}, save_dir="/tmp")
    # Wait for completion event.
    events: list[InferenceEvent] = []
    for _ in range(5):
        try:
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            break
        events.append(event)
        if event.stage == JobStage.COMPLETED:
            break
    await svc.stop()
    assert events[0].stage == JobStage.QUEUED
    assert events[-1].stage == JobStage.COMPLETED
    assert any(e.stage == JobStage.COMPLETED and e.file_path == f"/tmp/{job.uid}.glb" for e in events)
    assert len(stub.calls) == 1
    assert stub.calls[0]["uid"] == job.uid


@pytest.mark.asyncio
async def test_serial_execution(service_with_stub: tuple[InferenceService, _StubWorker]) -> None:
    """Two submissions must not run in parallel."""
    svc, _ = service_with_stub
    await svc.start()
    j1 = await svc.submit({"type": "text_to_3d", "prompt": "a"}, save_dir="/tmp")
    j2 = await svc.submit({"type": "text_to_3d", "prompt": "b"}, save_dir="/tmp")
    await asyncio.gather(*[svc._queue.join() for _ in range(2)])
    await svc.stop()
    assert j1.uid != j2.uid


@pytest.mark.asyncio
async def test_capabilities_without_worker(service_with_stub: tuple[InferenceService, _StubWorker]) -> None:
    svc, _ = service_with_stub
    caps = svc.capabilities()
    # Nothing loaded yet, but the structure is complete.
    assert caps["modes"]["text"]["available"] is False
    assert caps["models"]["shape"]["loaded"] is False
    assert "fast" in caps["presets"]


@pytest.mark.asyncio
async def test_capabilities_with_loaded_worker(
    service_with_stub: tuple[InferenceService, _StubWorker],
) -> None:
    svc, stub = service_with_stub
    # Pretend a shape pipeline is loaded.
    svc._worker = stub
    stub.pipeline = object()
    caps = svc.capabilities()
    assert caps["modes"]["image"]["available"] is True
    assert caps["models"]["shape"]["loaded"] is True


@pytest.mark.asyncio
async def test_cancel_removes_job(service_with_stub: tuple[InferenceService, _StubWorker]) -> None:
    svc, _ = service_with_stub
    await svc.start()
    job = await svc.submit({"type": "text_to_3d", "prompt": "x"}, save_dir="/tmp")
    assert job.uid in svc.jobs
    cancelled = await svc.cancel(job.uid)
    assert cancelled is True
    assert job.uid not in svc.jobs
    # Cancelling again returns False (idempotent).
    assert (await svc.cancel(job.uid)) is False
    await svc.stop()


@pytest.mark.asyncio
async def test_cancelled_queued_job_is_not_executed(
    service_with_stub: tuple[InferenceService, _StubWorker],
) -> None:
    svc, stub = service_with_stub
    job = await svc.submit({"type": "text_to_3d", "prompt": "x"}, save_dir="/tmp")
    assert await svc.cancel(job.uid) is True

    await svc.start()
    await svc._queue.join()
    await svc.stop()

    assert stub.calls == []


@pytest.mark.asyncio
async def test_active_job_cannot_be_cancelled(
    service_with_stub: tuple[InferenceService, _StubWorker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, stub = service_with_stub
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_execute(self: InferenceService, job: InferenceJob) -> None:
        self._worker = stub
        entered.set()
        await release.wait()
        self._publish(
            InferenceEvent(
                uid=job.uid,
                stage=JobStage.COMPLETED,
                file_path=stub.generate(job.uid, job.params, job.save_dir),
            )
        )

    monkeypatch.setattr(InferenceService, "_execute", blocking_execute)
    await svc.start()
    job = await svc.submit({"type": "text_to_3d", "prompt": "x"}, save_dir="/tmp")
    await entered.wait()

    assert await svc.cancel(job.uid) is False

    release.set()
    await svc._queue.join()
    await svc.stop()
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_queue_rejects_jobs_over_configured_capacity() -> None:
    svc = InferenceService(device="cpu", save_dir="/tmp", max_queue_size=1)
    first = await svc.submit({"type": "text_to_3d", "prompt": "first"})

    with pytest.raises(asyncio.QueueFull):
        await svc.submit({"type": "text_to_3d", "prompt": "second"})

    assert svc._queue.qsize() == 1
    assert set(svc.jobs) == {first.uid}


@pytest.mark.asyncio
async def test_stop_drains_full_queue_without_blocking() -> None:
    svc = InferenceService(device="cpu", save_dir="/tmp", max_queue_size=1)
    subscriber = svc.subscribe()
    job = await svc.submit({"type": "text_to_3d", "prompt": "queued"})

    await asyncio.wait_for(svc.stop(), timeout=0.2)

    assert svc._queue.empty()
    assert job.uid not in svc.jobs
    assert subscriber.get_nowait().stage == JobStage.CANCELLED


@pytest.mark.asyncio
async def test_warmup_returns_while_model_weights_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = InferenceService(device="cpu", save_dir="/tmp")
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeModelWorker:
        def __init__(self, **_kwargs) -> None:
            self.pipeline = None

        def warmup(self) -> None:
            self.pipeline = object()

    async def fake_to_thread(func, /, *args, **kwargs):
        if func is FakeModelWorker:
            return FakeModelWorker()
        started.set()
        await release.wait()
        return func(*args, **kwargs)

    monkeypatch.setattr("hy3dgen.inference.ModelWorker", FakeModelWorker)
    monkeypatch.setattr("hy3dgen.api.inference_service.asyncio.to_thread", fake_to_thread)

    result = await asyncio.wait_for(svc.warmup(), timeout=0.1)
    assert result == "loading"
    await started.wait()
    assert svc.warmup_loading
    release.set()
    await svc._warmup_task
    assert svc.warmup_state == "loaded"


@pytest.mark.asyncio
async def test_model_status_reflects_shared_warmup_state() -> None:
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.routes import get_model_status

    svc = InferenceService(device="cpu", save_dir="/tmp")
    svc._warmup_state = "loading"
    svc._warmup_started_at = "2026-10-08T12:00:00Z"
    manager = PriorityRequestManager(device="cpu", inference_service=svc)

    status = await get_model_status(manager)

    assert status.loading is True
    assert status.started_at == svc.warmup_started_at


def test_base64_decoder_enforces_decoded_size_limit() -> None:
    import base64

    from hy3dgen.inference import decode_base64

    payload = base64.b64encode(b"1234").decode("ascii")
    with pytest.raises(ValueError, match="maximum size"):
        decode_base64(payload, max_bytes=3)


def test_slow_service_subscriber_keeps_only_latest_event() -> None:
    svc = InferenceService(device="cpu", save_dir="/tmp")
    queue = svc.subscribe()
    svc._publish(InferenceEvent(uid="a", stage=JobStage.QUEUED))
    svc._publish(InferenceEvent(uid="a", stage=JobStage.SHAPE_GENERATION))
    svc._publish(InferenceEvent(uid="a", stage=JobStage.COMPLETED))

    assert queue.qsize() == 1
    assert queue.get_nowait().stage == JobStage.COMPLETED


@pytest.mark.asyncio
async def test_subscribe_unsubscribe(service_with_stub: tuple[InferenceService, _StubWorker]) -> None:
    svc, _ = service_with_stub
    q = svc.subscribe()
    assert q in svc._subscribers
    svc.unsubscribe(q)
    assert q not in svc._subscribers
    # Idempotent.
    svc.unsubscribe(q)


@pytest.mark.asyncio
async def test_submit_rejects_after_stop() -> None:
    svc = InferenceService(device="cpu", save_dir="/tmp")
    await svc.stop()
    with pytest.raises(RuntimeError, match="stopped"):
        await svc.submit({"type": "text_to_3d", "prompt": "x"}, save_dir="/tmp")
