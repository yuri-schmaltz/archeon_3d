"""Tests for Etapas 3, 4 and 5.

Covers:
- /v1/library paginated endpoint
- /v1/capabilities combined with admin stats
- SSE list payload contains stage fields when set
- JobResponse serialization drops None values for slim SSE
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from hy3dgen.api import deps, server as server_module
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import JobResponse, JobStatus, LibraryResponse


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
    mgr.queue = asyncio.Queue()
    return mgr


@pytest.fixture
def override_manager(tmp_path, monkeypatch):
    """Replace the app's manager dep with one bound to a temp DB.

    Avoids changing ``SAVE_DIR`` (used by other tests via direct import)
    by simply patching the manager dependency — the server keeps using
    the original SAVE_DIR for file I/O.
    """
    from hy3dgen.api import server as server_module

    mgr = _build_manager(tmp_path)
    mgr.jobs = {}  # wipe jobs rehydrated by the lifespan
    server_module.app.dependency_overrides[deps.get_manager] = lambda: mgr
    yield mgr
    server_module.app.dependency_overrides.pop(deps.get_manager, None)




# ---------------------------------------------------------------------------
# /v1/library
# ---------------------------------------------------------------------------


def test_library_lists_all_jobs(override_manager):
    """Library lists every job, paginated by limit/offset."""
    mgr = override_manager
    for i in range(5):
        mgr.jobs[f"u{i}"] = JobResponse(
            uid=f"u{i}",
            status=JobStatus.COMPLETED,
            created_at=f"2026-10-04T10:0{i}:00+00:00",
        )
    with TestClient(server_module.app) as client:
        r = client.get("/v1/library?page=1&page_size=3")
        assert r.status_code == 200
        body = LibraryResponse(**r.json())
        assert body.total == 5
        assert len(body.items) == 3
        assert body.has_more is True

        r = client.get("/v1/library?page=2&page_size=3")
        body = LibraryResponse(**r.json())
        assert len(body.items) == 2
        assert body.has_more is False


def test_library_filters_by_status(override_manager):
    mgr = override_manager
    mgr.jobs["done"] = JobResponse(
        uid="done", status=JobStatus.COMPLETED, created_at="2026-10-04T10:00:00+00:00"
    )
    mgr.jobs["fail"] = JobResponse(
        uid="fail", status=JobStatus.FAILED, created_at="2026-10-04T10:01:00+00:00"
    )
    mgr.jobs["pend"] = JobResponse(
        uid="pend", status=JobStatus.QUEUED, created_at="2026-10-04T10:02:00+00:00"
    )
    with TestClient(server_module.app) as client:
        r = client.get("/v1/library?status=failed")
        body = LibraryResponse(**r.json())
        assert body.total == 1
        assert body.items[0].uid == "fail"

        r = client.get("/v1/library?status=queued")
        body = LibraryResponse(**r.json())
        assert body.total == 1
        assert body.items[0].uid == "pend"


def test_library_search_matches_payload(override_manager, tmp_path):
    """Search matches across the request payload's JSON text."""
    import asyncio

    # Use the manager from the fixture so the test sees exactly the
    # in-memory + persistent state we set up.
    mgr = override_manager
    store = JobStore(str(tmp_path / "jobs.db"))
    mgr.store = store
    # Clear any leftover records.
    async def reset():
        for uid in list(mgr.jobs):
            del mgr.jobs[uid]
    asyncio.run(reset())
    server_module.app.dependency_overrides[deps.get_manager] = lambda: mgr
    try:
        async def seed():
            await store.upsert(
                JobResponse(
                    uid="cat-1",
                    status=JobStatus.COMPLETED,
                    created_at="2026-10-04T10:00:00+00:00",
                ),
                request_payload={"text": "a small red cube", "type": "text_to_3d"},
            )
            await store.upsert(
                JobResponse(
                    uid="dog-1",
                    status=JobStatus.COMPLETED,
                    created_at="2026-10-04T10:01:00+00:00",
                ),
                request_payload={"text": "a green dog", "type": "text_to_3d"},
            )
        asyncio.run(seed())
        with TestClient(server_module.app) as client:
            r = client.get("/v1/library?q=red")
            body = LibraryResponse(**r.json())
            assert body.total == 1, body
            assert body.items[0].uid == "cat-1"
    finally:
        server_module.app.dependency_overrides.pop(deps.get_manager, None)


def test_library_search_in_memory(override_manager):
    """When no store is present, library searches in-memory uids/uid."""
    mgr = override_manager
    mgr.store = None
    mgr.jobs["abc-123"] = JobResponse(
        uid="abc-123",
        status=JobStatus.COMPLETED,
        created_at="2026-10-04T10:00:00+00:00",
        request_type="text_to_3d",
    )
    mgr.jobs["xyz-999"] = JobResponse(
        uid="xyz-999",
        status=JobStatus.COMPLETED,
        created_at="2026-10-04T10:01:00+00:00",
        request_type="image_to_3d",
    )
    with TestClient(server_module.app) as client:
        r = client.get("/v1/library?q=abc")
        body = LibraryResponse(**r.json())
        assert body.total == 1
        assert body.items[0].uid == "abc-123"

        r = client.get("/v1/library?q=image")
        body = LibraryResponse(**r.json())
        assert body.total == 1
        assert body.items[0].uid == "xyz-999"


# ---------------------------------------------------------------------------
# Capabilities / admin stats combined for the System page
# ---------------------------------------------------------------------------


def test_capabilities_endpoint_returns_static_and_dynamic_fields(override_manager):
    with TestClient(server_module.app) as client:
        r = client.get("/v1/capabilities")
        assert r.status_code == 200
        body = r.json()
        assert set(body["modes"]) == {"text", "image", "multiview", "texture"}
        assert set(body["presets"]) == {"fast", "balanced", "detailed"}
        assert body["limits"]["image_bytes"] == 10 * 1024 * 1024
        assert "version" in body
        assert isinstance(body["version"], str)


def test_admin_stats_endpoint_exposes_counts(override_manager):
    with TestClient(server_module.app) as client:
        r = client.get("/v1/admin/stats")
        assert r.status_code == 200
        body = r.json()
        assert "queue_depth" in body
        assert "jobs_in_memory" in body
        assert "by_status" in body
        assert "persistence_enabled" in body


# ---------------------------------------------------------------------------
# SSE payload includes stage when set
# ---------------------------------------------------------------------------


def test_slim_payload_carries_stage_and_progress():
    response = JobResponse(
        uid="abc",
        status=JobStatus.PROCESSING,
        created_at="2026-10-04T10:00:00+00:00",
        stage="texturing",
        stage_progress=0.42,
    )
    payload = response.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    assert payload["stage"] == "texturing"
    assert payload["stage_progress"] == 0.42
    assert "error" not in payload
    assert "file_path" not in payload


def test_slim_payload_drops_explicit_none_stage():
    response = JobResponse(
        uid="abc",
        status=JobStatus.QUEUED,
        created_at="2026-10-04T10:00:00+00:00",
        stage=None,
    )
    payload = response.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    assert "stage" not in payload


# ---------------------------------------------------------------------------
# manager.set_stage clamp + propagation
# ---------------------------------------------------------------------------


def test_set_stage_clamps_progress(tmp_path):
    mgr = _build_manager(tmp_path)
    job = JobResponse(
        uid="u", status=JobStatus.PROCESSING, created_at="2026-10-04T10:00:00+00:00"
    )
    mgr.jobs[job.uid] = job
    mgr.set_stage("u", "loading_model", 2.0)
    assert job.stage_progress == 1.0
    mgr.set_stage("u", "loading_model", -0.5)
    assert job.stage_progress == 0.0
    mgr.set_stage("u", "loading_model", None)
    assert job.stage_progress == 0.0
