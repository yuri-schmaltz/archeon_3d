"""End-to-end integration test for the PolyForge API.

Exercises the real FastAPI app with the GPU-bound ``ModelWorker`` replaced
by a stub that:
- Records the params it received
- Returns a fake file path under a temp dir

This covers the full HTTP path: request validation, auth, job submission,
polling, file mount, status reporting, and CORS.
"""
import os
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

try:
    import torch  # noqa: F401
    from fastapi.testclient import TestClient
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    TestClient = None  # type: ignore[assignment]
    PriorityRequestManager = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch/fastapi not installed",
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _ImmediateManager:
    """Stub that runs jobs synchronously inside submit_job (no real worker)."""

    def __init__(self):
        self.jobs: dict = {}
        self.worker = MagicMock()
        self.last_error: str | None = None
        self._counter = 0

    async def start(self): pass
    async def stop(self): pass

    def _resolve_path(self, uid: str, fmt: str) -> str:
        # Mirror what the real manager does: put the file under SAVE_DIR.
        from hy3dgen.api.config import SAVE_DIR
        os.makedirs(SAVE_DIR, exist_ok=True)
        return os.path.join(SAVE_DIR, f"{uid}.{fmt}")

    async def submit_job(self, request, save_dir: str, priority: int = 10) -> str:
        import uuid
        from datetime import datetime
        from hy3dgen.api.manager import PriorityRequestManager
        uid = str(uuid.uuid4())
        # Mark the job as processing.
        job = JobResponse(
            uid=uid,
            status=JobStatus.PROCESSING,
            created_at=datetime.utcnow().isoformat(),
        )
        self.jobs[uid] = job
        # Synchronously "generate" by writing a tiny fake mesh file.
        params = request.model_dump()
        fmt = params.get("format", "glb")
        file_path = self._resolve_path(uid, fmt)
        with open(file_path, "wb") as f:
            f.write(b"fake glb content for " + uid.encode())
        # Promote to completed.
        job.status = JobStatus.COMPLETED
        job.file_path = file_path
        job.completed_at = datetime.utcnow().isoformat()
        return uid

    def get_job(self, uid):
        return self.jobs.get(uid)

    def cancel_job(self, uid):
        if uid in self.jobs and self.jobs[uid].status == JobStatus.QUEUED:
            self.jobs[uid].status = JobStatus.CANCELLED


@contextmanager
def _patched_app(stub_manager):
    """Build a TestClient with the manager stubbed in."""
    from hy3dgen.api import server
    from hy3dgen.api import routes as routes_module

    # Clean any leftover env from previous tests.
    for k in ("POLYFORGE_API_KEY", "POLYFORGE_CORS_ORIGINS", "POLYFORGE_ALLOW_CREDENTIALS"):
        os.environ.pop(k, None)

    server.app.dependency_overrides[PriorityRequestManager] = lambda: stub_manager
    server.app.dependency_overrides[routes_module.__dict__['get_manager']] = (
        lambda: stub_manager
    )
    with TestClient(server.app) as client:
        yield client
    server.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSubmitAndPoll:
    def test_text_to_3d_full_flow(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            # Submit
            r = client.post(
                "/v1/jobs",
                json={"type": "text_to_3d", "prompt": "a red chair", "format": "glb"},
            )
            assert r.status_code == 202, r.text
            uid = r.json()["uid"]

            # Poll status. Stub completes synchronously so it should be done.
            r = client.get(f"/v1/jobs/{uid}")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "completed"
            assert data["file_path"].endswith(f"{uid}.glb")

            # Download
            r = client.get(f"/files/{uid}.glb")
            assert r.status_code == 200
            assert r.content.startswith(b"fake glb content")

    def test_image_to_3d_full_flow(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.post(
                "/v1/jobs",
                json={
                    "type": "image_to_3d",
                    "image": "aGVsbG8=",
                    "format": "obj",
                },
            )
            assert r.status_code == 202
            uid = r.json()["uid"]
            r = client.get(f"/v1/jobs/{uid}")
            assert r.status_code == 200
            assert r.json()["status"] == "completed"
            assert r.json()["file_path"].endswith(".obj")

    def test_multiview_full_flow(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.post(
                "/v1/jobs",
                json={
                    "type": "multiview",
                    "front": "Zg==",
                    "back": "Zg==",
                    "left": "Zg==",
                    "right": "Zg==",
                },
            )
            assert r.status_code == 202
            assert r.json()["uid"]

    def test_texture_mesh_full_flow(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.post(
                "/v1/jobs",
                json={
                    "type": "texture_mesh",
                    "mesh": "Z2xi",
                    "image": "aW1hZ2U=",
                    "format": "glb",
                },
            )
            assert r.status_code == 202

    def test_unknown_type_returns_422(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.post(
                "/v1/jobs",
                json={"type": "voice_to_3d", "prompt": "x"},
            )
            assert r.status_code == 422


class TestListAndCancel:
    def test_list_returns_recent_jobs(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            # Submit 2 jobs
            client.post("/v1/jobs", json={"type": "text_to_3d", "prompt": "a"})
            client.post("/v1/jobs", json={"type": "text_to_3d", "prompt": "b"})
            r = client.get("/v1/jobs")
            assert r.status_code == 200
            assert len(r.json()) >= 2

    def test_get_unknown_job_404(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.get("/v1/jobs/does-not-exist")
            assert r.status_code == 404


class TestHealthCheck:
    def test_health_returns_extended_payload(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.get("/health")
            assert r.status_code == 200
            data = r.json()
            # All extended fields should be present.
            assert "version" in data
            assert "model_loaded" in data
            assert "queue_size" in data
            assert "auth_required" in data
            assert "last_error" in data
            assert data["status"] == "ok"
            assert data["auth_required"] is False  # no env key set in fixture

    def test_health_reflects_auth_when_key_set(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            with patch.dict(os.environ, {"POLYFORGE_API_KEY": "test"}):
                # Reload the auth module so the env-derived key is re-read.
                import importlib
                from hy3dgen.api import auth
                importlib.reload(auth)
                r = client.get("/health")
                assert r.json()["auth_required"] is True


class TestCORS:
    def test_cors_preflight_with_explicit_origin(self):
        stub = _ImmediateManager()
        with _patched_app(stub) as client:
            r = client.options(
                "/v1/jobs",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )
            # CORS middleware should accept the preflight and return the
            # appropriate Access-Control-Allow-Origin header.
            assert r.status_code in (200, 204)
            assert r.headers.get("access-control-allow-origin") in (
                "http://localhost:5173", "*",
            )
