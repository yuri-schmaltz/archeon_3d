"""End-to-end test for /v1/jobs/{uid}/download-url + signed file fetch."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hy3dgen.api import server as server_module
from hy3dgen.api.config import SAVE_DIR
from hy3dgen.api.deps import get_manager
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.schemas import JobResponse, JobStatus


class _NoOpStore:
    async def delete(self, uid: str) -> None:  # pragma: no cover - never called
        return None


class _StubManager(PriorityRequestManager):
    """Manager that exposes a completed job without booting the worker loop."""

    def __init__(self) -> None:
        super().__init__(device="cpu", store=None)
        from hy3dgen.api.timeutils import utc_now

        self._stub_job = JobResponse(
            uid="abc-123",
            status=JobStatus.COMPLETED,
            created_at=utc_now(),
            updated_at=utc_now(),
            file_path=str(Path(SAVE_DIR) / "abc-123.glb"),
        )
        self.jobs[self._stub_job.uid] = self._stub_job


@pytest.fixture
def signed_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[TestClient, Path]:
    monkeypatch.setenv("POLYFORGE_API_KEY", "secret-key")
    # Write a real file in the existing SAVE_DIR (StaticFiles is bound at import time).
    artifact = Path(SAVE_DIR) / "abc-123.glb"
    artifact.write_bytes(b"\x00fake-glb-bytes")
    # Patch the manager's job to point at this real artifact.
    stub = _StubManager()
    stub.jobs["abc-123"].file_path = str(artifact)
    app = server_module.app
    app.dependency_overrides[get_manager] = lambda: stub
    yield TestClient(app), artifact
    # Cleanup the file we wrote into the real SAVE_DIR.
    import contextlib

    with contextlib.suppress(FileNotFoundError):
        artifact.unlink()
    app.dependency_overrides.pop(get_manager, None)


def test_download_url_endpoint_returns_signed_url(signed_env: tuple[TestClient, Path]) -> None:
    client, _ = signed_env
    headers = {"X-API-Key": "secret-key"}
    resp = client.get("/v1/jobs/abc-123/download-url", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"].startswith("http://testserver/files/abc-123.glb?")
    assert body["ttl_seconds"] == 3600
    assert body["expires_at"] > 0


def test_signed_url_actually_serves_file(signed_env: tuple[TestClient, Path]) -> None:
    client, _ = signed_env
    resp = client.get("/v1/jobs/abc-123/download-url", headers={"X-API-Key": "secret-key"})
    signed_url = resp.json()["url"]
    # Hit the signed URL WITHOUT the API key — it should serve the file.
    full = signed_url.replace("http://testserver", "")
    fetch = client.get(full)
    assert fetch.status_code == 200, fetch.text
    assert fetch.content == b"\x00fake-glb-bytes"


def test_unsigned_download_without_key_is_401(signed_env: tuple[TestClient, Path]) -> None:
    client, _ = signed_env
    # Direct /files/ request without API key must be rejected.
    fetch = client.get("/files/abc-123.glb")
    assert fetch.status_code == 401


def test_unsigned_download_with_api_key_works(signed_env: tuple[TestClient, Path]) -> None:
    client, _ = signed_env
    fetch = client.get("/files/abc-123.glb", headers={"X-API-Key": "secret-key"})
    assert fetch.status_code == 200
    assert fetch.content == b"\x00fake-glb-bytes"


def test_unknown_job_404(signed_env: tuple[TestClient, Path]) -> None:
    client, _ = signed_env
    resp = client.get(
        "/v1/jobs/does-not-exist/download-url",
        headers={"X-API-Key": "secret-key"},
    )
    assert resp.status_code == 404


def test_no_signing_key_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
    monkeypatch.delenv("POLYFORGE_URL_SIGNING_KEY", raising=False)
    stub = _StubManager()
    app = server_module.app
    app.dependency_overrides[get_manager] = lambda: stub
    try:
        client = TestClient(app)
        resp = client.get("/v1/jobs/abc-123/download-url")
        # Without auth configured the route requires no header, so this
        # falls through to build_signed_url and returns 503.
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_manager, None)
