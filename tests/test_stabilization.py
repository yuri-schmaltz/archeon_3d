"""Regression coverage across API routes, queue lifecycle and inference dispatch."""

import asyncio
import base64
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import httpx
from fastapi import Depends, FastAPI

from hy3dgen.api.auth import require_api_key
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.routes import router
from hy3dgen.api.schemas import GenerationRequest, JobResponse, JobStatus, TextTo3DRequest
from hy3dgen.api.timeutils import timestamp, utc_now
from hy3dgen.inference import ModelWorker


def app_for(manager):
    app = FastAPI()
    app.state.manager = manager
    app.include_router(router, dependencies=[Depends(require_api_key)])
    return app


async def test_http_cancel_persists_and_completed_sse_closes(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCHEON_API_KEY", raising=False)
    store = JobStore(str(tmp_path / "jobs.db"))
    manager = PriorityRequestManager(device="cpu", store=store)
    uid = await manager.submit_job(TextTo3DRequest(prompt="chair"), str(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_for(manager)), base_url="http://test"
    ) as client:
        response = await client.delete(f"/v1/jobs/{uid}")
        assert response.status_code == 200
        restored = await store.get(uid)
        assert restored.status == JobStatus.CANCELLED
        assert restored.request_type == "text_to_3d"
        assert restored.updated_at is not None
        response = await asyncio.wait_for(client.get(f"/v1/jobs/{uid}/events"), 2)
        assert response.status_code == 200
        assert "event: status" in response.text
        payload = json.loads(
            next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        )
        assert payload["status"] == "cancelled"
        assert uid not in manager._subscribers


async def test_processing_job_cannot_be_cancelled_and_auth_is_enforced(monkeypatch):
    monkeypatch.setenv("ARCHEON_API_KEY", "test-secret")
    manager = PriorityRequestManager(device="cpu")
    manager.jobs["active"] = JobResponse(
        uid="active", status=JobStatus.PROCESSING, created_at=utc_now()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_for(manager)), base_url="http://test"
    ) as client:
        assert (await client.delete("/v1/jobs/active")).status_code == 401
        response = await client.delete("/v1/jobs/active", headers={"X-API-Key": "test-secret"})
        assert response.status_code == 409
        assert manager.jobs["active"].status == JobStatus.PROCESSING


async def test_cancelled_queue_item_does_not_break_following_job(tmp_path, caplog):
    manager = PriorityRequestManager(device="cpu", max_age_seconds=0)
    manager.worker = Mock(generate=Mock(return_value=str(tmp_path / "mesh.glb")))
    cancelled = await manager.submit_job(TextTo3DRequest(prompt="skip"), str(tmp_path))
    await manager.cancel_job(cancelled)
    next_uid = await manager.submit_job(TextTo3DRequest(prompt="run"), str(tmp_path))
    await manager.start()
    await asyncio.wait_for(manager.queue.join(), 2)
    await manager.stop()
    assert manager.jobs[cancelled].status == JobStatus.CANCELLED
    assert manager.jobs[next_uid].status == JobStatus.COMPLETED
    manager.worker.generate.assert_called_once()
    assert "task_done() called too many times" not in caplog.text


async def test_shutdown_drains_unstarted_jobs(tmp_path):
    manager = PriorityRequestManager(device="cpu")
    uid = await manager.submit_job(TextTo3DRequest(prompt="pending"), str(tmp_path))
    await manager.stop()
    assert manager.jobs[uid].status == JobStatus.CANCELLED
    assert manager.queue.empty()
    await asyncio.wait_for(manager.queue.join(), 1)


async def test_automatic_cleanup_applies_history_limit():
    manager = PriorityRequestManager(device="cpu", max_history=2, max_age_seconds=0)
    for uid in ("one", "two", "three"):
        manager.jobs[uid] = JobResponse(uid=uid, status=JobStatus.COMPLETED, created_at=utc_now())
    await manager._aggressive_cleanup()
    assert len(manager.jobs) == 2


async def test_old_database_migrates_without_losing_payload(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (uid TEXT PRIMARY KEY, status TEXT, created_at TEXT, completed_at TEXT, file_path TEXT, error TEXT, request_blob TEXT)"
        )
        connection.execute(
            "INSERT INTO jobs VALUES ('old', 'queued', ?, NULL, NULL, NULL, ?)",
            (utc_now(), json.dumps({"text": "chair"})),
        )
    store = JobStore(str(path))
    job = await store.get("old")
    job.request_type = "text_to_3d"
    job.updated_at = utc_now()
    await store.upsert(job)
    records = [record async for record in store.restore_all()]
    assert records[0][1] == {"text": "chair"}
    assert records[0][0].request_type == "text_to_3d"


async def test_retention_accepts_utc_and_offsets(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    now = datetime.now(timezone.utc)
    for uid, age in (("recent", 5), ("old", 120)):
        created = (
            (now - timedelta(seconds=age)).astimezone(timezone(timedelta(hours=-3))).isoformat()
        )
        await store.upsert(JobResponse(uid=uid, status=JobStatus.COMPLETED, created_at=created))
    assert await store.delete_older_than(60) == 1
    assert await store.get("recent") is not None
    assert timestamp("2026-01-01T00:00:00") == timestamp("2026-01-01T00:00:00Z")


def image_base64():
    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (4, 4), "red").save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


def test_multiview_reaches_shape_pipeline_and_exports_real_glb(tmp_path, monkeypatch):
    import trimesh

    worker = ModelWorker(device="cpu", enable_tex=True)
    mesh = trimesh.creation.box()
    pipeline = Mock(return_value=[mesh])
    monkeypatch.setattr(worker, "_load_shape_pipeline", Mock(return_value=pipeline))
    monkeypatch.setattr(worker, "rembg", lambda image: image)
    paint = Mock(return_value=mesh)
    monkeypatch.setattr(worker, "_texture", paint)
    request = GenerationRequest(
        views={key: image_base64() for key in ("front", "back", "left", "right")}, texture=True
    )
    path = worker.generate("mv", request.to_internal_request().model_dump(), str(tmp_path))
    assert Path(path).read_bytes()[:4] == b"glTF"
    assert set(pipeline.call_args.kwargs["image"]) == {"front", "back", "left", "right"}
    assert pipeline.call_args.kwargs["output_type"] == "trimesh"
    assert paint.call_args.args[1] is pipeline.call_args.kwargs["image"]["front"]
    worker._load_shape_pipeline.assert_called_once_with(True)


def test_remove_background_false_is_respected(tmp_path, monkeypatch):
    import trimesh

    worker = ModelWorker(device="cpu")
    monkeypatch.setattr(
        worker, "rembg", Mock(side_effect=AssertionError("must not remove background"))
    )
    monkeypatch.setattr(
        worker,
        "_load_shape_pipeline",
        Mock(return_value=Mock(return_value=[trimesh.creation.box()])),
    )
    path = worker.generate(
        "image", {"image": image_base64(), "remove_background": False}, str(tmp_path)
    )
    assert trimesh.load(path, force="mesh").vertices.shape[0] > 0
    worker.rembg.assert_not_called()


def test_dotenv_key_and_explicit_empty_override(tmp_path, monkeypatch):
    from hy3dgen.api.auth import get_api_key

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ARCHEON_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ARCHEON_API_KEY=dotenv-test-key\n")
    assert get_api_key() == "dotenv-test-key"
    monkeypatch.setenv("ARCHEON_API_KEY", "")
    assert get_api_key() is None


async def test_notifications_capture_each_transition():
    manager = PriorityRequestManager(device="cpu")
    manager.jobs["job"] = JobResponse(uid="job", status=JobStatus.QUEUED, created_at=utc_now())
    queue = await manager.subscribe("job")
    manager.jobs["job"].status = JobStatus.PROCESSING
    manager._notify(manager.jobs["job"])
    manager.jobs["job"].status = JobStatus.COMPLETED
    manager._notify(manager.jobs["job"])
    assert [queue.get_nowait().status for _ in range(3)] == [
        JobStatus.QUEUED,
        JobStatus.PROCESSING,
        JobStatus.COMPLETED,
    ]


def test_api_startup_applies_environment_overrides(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "ARCHEON_SAVE_DIR": str(tmp_path / "outputs"),
        "ARCHEON_JOB_DB": "",
        "ARCHEON_DEVICE": "cpu",
        "ARCHEON_MAX_HISTORY": "12",
        "ARCHEON_MODEL": "test/model",
        "ARCHEON_MODEL_SUBFOLDER": "test-folder",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio, json
from hy3dgen.api.server import app, lifespan
from hy3dgen.api.config import SAVE_DIR
async def main():
    async with lifespan(app):
        manager = app.state.manager
        print(json.dumps([SAVE_DIR, manager.device, manager.max_history, manager.model_path, manager.model_subfolder]))
asyncio.run(main())
""",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [
        str(tmp_path / "outputs"),
        "cpu",
        12,
        "test/model",
        "test-folder",
    ]
