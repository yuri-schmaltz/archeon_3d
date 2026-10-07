"""Tests for Etapa 2 (Fase 2) additions.

Covers:
- GET /v1/capabilities
- stage / stage_progress on JobResponse
- /files requires X-API-Key when auth is configured
- SSE payloads use exclude_defaults + exclude_none
- cleanup_files_older_than separates disk retention from DB retention
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import (
    CapabilitiesResponse,
    JobResponse,
    JobStatus,
)

# ---------------------------------------------------------------------------
# Capabilities endpoint
# ---------------------------------------------------------------------------


def _build_manager(tmp_path, *, store: JobStore | None = None) -> PriorityRequestManager:
    mgr = PriorityRequestManager(
        device="cpu",
        max_history=10,
        store=store,
        max_age_seconds=3600,
        model_path="stub/shape",
        model_subfolder="s",
        multiview_model="stub/mv",
        multiview_subfolder="s",
    )
    mgr.queue = asyncio.Queue()  # ensure an event-loop-free queue
    return mgr


def test_capabilities_response_shape():
    """CapabilitiesResponse validates a representative payload."""
    payload = {
        "modes": {
            "text": {"available": True, "reason": None, "requires": []},
            "image": {"available": True, "reason": None, "requires": []},
            "multiview": {"available": False, "reason": "Model not loaded.", "requires": []},
            "texture": {"available": True, "reason": None, "requires": []},
        },
        "models": {
            "shape": {"id": "stub/shape", "subfolder": "s", "loaded": False},
        },
        "presets": {
            "fast": {"steps": 5, "guidance": 5.0, "octree_resolution": 192},
            "balanced": {"steps": 50, "guidance": 5.0, "octree_resolution": 256},
            "detailed": {"steps": 100, "guidance": 7.5, "octree_resolution": 384},
        },
        "limits": {
            "image_bytes": 10485760,
            "mesh_bytes": 31457280,
            "queue_depth": 64,
            "body_bytes": 67108864,
        },
        "version": "2.1.0.post7",
    }
    parsed = CapabilitiesResponse(**payload)
    assert parsed.modes["text"].available is True
    assert parsed.modes["multiview"].available is False
    assert parsed.presets["fast"].steps == 5
    assert parsed.limits.image_bytes == 10 * 1024 * 1024


def test_manager_capabilities_reports_unloaded():
    """A fresh manager reports all modes as unavailable."""
    mgr = _build_manager(pathlib.Path("/tmp"))
    snap = mgr.capabilities()
    assert set(snap["modes"]) == {"text", "image", "multiview", "texture"}
    assert set(snap["models"]) == {"shape", "multiview", "texture", "text_to_image"}
    assert set(snap["presets"]) == {"fast", "balanced", "detailed"}
    assert snap["limits"]["image_bytes"] == 10 * 1024 * 1024
    assert snap["limits"]["body_bytes"] == 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# Stage progress
# ---------------------------------------------------------------------------


def test_job_response_carries_stage_fields():
    """JobResponse exposes stage + stage_progress and defaults None."""
    response = JobResponse(
        uid="abc",
        status=JobStatus.PROCESSING,
        created_at="2026-10-04T10:00:00+00:00",
        stage="shape_generation",
        stage_progress=0.42,
    )
    assert response.stage == "shape_generation"
    assert response.stage_progress == 0.42
    plain = JobResponse(uid="x", status=JobStatus.QUEUED, created_at="2026-10-04T10:00:00+00:00")
    assert plain.stage is None
    assert plain.stage_progress is None


def test_set_stage_updates_job():
    """set_stage mutates the in-memory job and clamps progress to [0, 1]."""
    mgr = _build_manager(pathlib.Path("/tmp"))
    job = JobResponse(
        uid="u1",
        status=JobStatus.PROCESSING,
        created_at="2026-10-04T10:00:00+00:00",
    )
    mgr.jobs[job.uid] = job
    mgr.set_stage("u1", "shape_generation", 0.4)
    assert job.stage == "shape_generation"
    assert job.stage_progress == 0.4
    # Progress is clamped to [0, 1].
    mgr.set_stage("u1", "exporting", 2.0)
    assert job.stage_progress == 1.0
    mgr.set_stage("u1", "exporting", -0.5)
    assert job.stage_progress == 0.0


# ---------------------------------------------------------------------------
# SSE slim payloads
# ---------------------------------------------------------------------------


def test_sse_payload_uses_exclude_defaults():
    """JobResponse.model_dump(exclude_defaults=True, exclude_none=True) drops
    fields that weren't set explicitly (e.g. stage when it's None)."""
    response = JobResponse(
        uid="u1",
        status=JobStatus.QUEUED,
        created_at="2026-10-04T10:00:00+00:00",
    )
    payload = response.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    # Fields that have defaults in the model definition should be gone.
    assert "stage" not in payload
    assert "stage_progress" not in payload
    assert "error" not in payload
    assert "file_path" not in payload
    # Required fields stay.
    assert payload["uid"] == "u1"
    assert payload["status"] == "queued"


def test_sse_payload_includes_stage_when_set():
    """When stage is set, it must appear in the slim payload."""
    response = JobResponse(
        uid="u1",
        status=JobStatus.PROCESSING,
        created_at="2026-10-04T10:00:00+00:00",
        stage="texturing",
        stage_progress=0.7,
    )
    payload = response.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    assert payload["stage"] == "texturing"
    assert payload["stage_progress"] == 0.7


# ---------------------------------------------------------------------------
# Retention split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_older_than_only_returns_terminal_records(tmp_path):
    """The new list_older_than helper only returns terminal jobs older than
    the cutoff."""
    db = str(tmp_path / "jobs.db")
    store = JobStore(db)
    await store.upsert(
        JobResponse(
            uid="old-completed",
            status=JobStatus.COMPLETED,
            created_at="2020-01-01T00:00:00+00:00",
        ),
        request_payload={"text": "old"},
    )
    await store.upsert(
        JobResponse(
            uid="active",
            status=JobStatus.QUEUED,
            created_at="2020-01-01T00:00:00+00:00",
        ),
        request_payload={"text": "queued"},
    )
    await store.upsert(
        JobResponse(
            uid="recent",
            status=JobStatus.COMPLETED,
            created_at="2099-01-01T00:00:00+00:00",
        ),
        request_payload={"text": "future"},
    )
    victims = await store.list_older_than(60)
    uids = {j.uid for j in victims}
    assert "old-completed" in uids
    assert "recent" not in uids
    assert "active" not in uids


@pytest.mark.asyncio
async def test_cleanup_files_older_than_removes_only_files(tmp_path):
    """cleanup_files_older_than removes files from disk but does NOT touch
    the DB rows. This is the desired split: DB and disk have independent
    retention policies."""
    db = str(tmp_path / "jobs.db")
    store = JobStore(db)
    save_dir = tmp_path / "artifacts"
    save_dir.mkdir()
    mesh_path = save_dir / "old.glb"
    mesh_path.write_bytes(b"GLB-fake")
    other_path = save_dir / "young.glb"
    other_path.write_bytes(b"GLB-fake")

    await store.upsert(
        JobResponse(
            uid="old",
            status=JobStatus.COMPLETED,
            created_at="2020-01-01T00:00:00+00:00",
            file_path=str(mesh_path),
        ),
        request_payload={"text": "old"},
    )
    await store.upsert(
        JobResponse(
            uid="young",
            status=JobStatus.COMPLETED,
            created_at="2099-01-01T00:00:00+00:00",
            file_path=str(other_path),
        ),
        request_payload={"text": "young"},
    )

    mgr = PriorityRequestManager(device="cpu", store=store)
    removed = await mgr.cleanup_files_older_than(60, save_dir=str(save_dir))
    assert removed == 1
    assert not mesh_path.exists()
    assert other_path.exists()
    # The DB still has BOTH records.
    assert (await store.count()) == 2


# ---------------------------------------------------------------------------
# /files auth protection
# ---------------------------------------------------------------------------


def test_files_protected_when_api_key_configured(monkeypatch, tmp_path):
    """When POLYFORGE_API_KEY is set, /files requires the matching header."""
    monkeypatch.setenv("POLYFORGE_API_KEY", "secret-key")
    import importlib
    import pathlib

    from hy3dgen.api import auth as auth_module, server as server_module

    importlib.reload(auth_module)
    importlib.reload(server_module)

    artifact = pathlib.Path(server_module.SAVE_DIR) / "test.glb"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"GLB-fake")

    try:
        client = TestClient(server_module.app)
        r = client.get("/files/test.glb")
        assert r.status_code == 401
        r = client.get("/files/test.glb", headers={"X-API-Key": "wrong"})
        assert r.status_code == 403
        r = client.get("/files/test.glb", headers={"X-API-Key": "secret-key"})
        assert r.status_code == 200
        assert r.content == b"GLB-fake"
    finally:
        artifact.unlink(missing_ok=True)
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)


def test_files_open_when_api_key_unset(tmp_path):
    """When POLYFORGE_API_KEY is empty, /files is publicly readable (dev mode)."""
    os.environ.pop("POLYFORGE_API_KEY", None)
    import importlib
    import pathlib

    from hy3dgen.api import auth as auth_module, server as server_module

    importlib.reload(auth_module)
    importlib.reload(server_module)

    artifact = pathlib.Path(server_module.SAVE_DIR) / "test-open.glb"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"GLB-open")

    try:
        client = TestClient(server_module.app)
        r = client.get("/files/test-open.glb")
        assert r.status_code == 200
        assert r.content == b"GLB-open"
    finally:
        artifact.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Body size limit
# ---------------------------------------------------------------------------


def test_body_size_limit_returns_413(tmp_path, monkeypatch):
    """Requests larger than the configured cap are rejected with 413."""
    os.environ.pop("POLYFORGE_API_KEY", None)
    import importlib

    from hy3dgen.api import auth as auth_module, server as server_module

    importlib.reload(auth_module)
    importlib.reload(server_module)

    client = TestClient(server_module.app)
    huge = b"x" * (65 * 1024 * 1024)
    r = client.post(
        "/v1/generate",
        content=huge,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
