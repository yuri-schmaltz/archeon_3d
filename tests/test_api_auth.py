"""
Tests for the PolyForge backend security middleware.

These run against a FastAPI ``TestClient`` with the GPU-bound routes mocked
out (the manager is replaced with a stub). The point of these tests is to
verify the auth + CORS contract, not the inference path.
"""
import os
import pytest

try:
    import torch  # noqa: F401
    from fastapi.testclient import TestClient

    from hy3dgen.api.auth import get_api_key, require_api_key
    from hy3dgen.api.manager import PriorityRequestManager
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    TestClient = None  # type: ignore[assignment]
    PriorityRequestManager = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch/fastapi not installed",
)


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient with the manager stubbed out so we never touch torch."""
    from hy3dgen.api import server
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api import routes as routes_module

    # Reset env-derived config before each test.
    for k in ("POLYFORGE_API_KEY", "POLYFORGE_CORS_ORIGINS", "POLYFORGE_ALLOW_CREDENTIALS"):
        monkeypatch.delenv(k, raising=False)

    class _StubManager:
        jobs: dict = {}
        async def start(self): pass
        async def stop(self): pass
        async def submit_job(self, *args, **kwargs):
            from hy3dgen.api.schemas import JobResponse, JobStatus
            job = JobResponse(
                uid="stub-uid",
                status=JobStatus.QUEUED,
                created_at="2025-01-01T00:00:00",
            )
            self.jobs[job.uid] = job
            return job.uid
        def get_job(self, uid):
            return self.jobs.get(uid)
        def cancel_job(self, uid): pass
        def list_jobs(self):
            return []

    class _StubProcessor:
        def process(self, *args, **kwargs):
            return ""

    server.app.dependency_overrides[PriorityRequestManager] = lambda: _StubManager()
    server.app.dependency_overrides[routes_module.__dict__['get_manager']] = (
        lambda: _StubManager()
    )
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuthDisabled:
    def test_no_key_env_allows_request(self, client):
        # /v1/jobs is behind require_api_key but no key is set, so it should pass.
        # The stub manager returns 'stub-uid' so we can match the response shape.
        r = client.post(
            "/v1/jobs",
            json={"type": "text_to_3d", "prompt": "x"},
        )
        # 202 from PriorityRequestManager.submit_job; the stub returns 'stub-uid'
        # but we only verify the auth layer let the request through.
        assert r.status_code in (202, 500)
        assert r.status_code != 401
        assert r.status_code != 403


class TestAuthEnabled:
    def test_missing_header_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("POLYFORGE_API_KEY", "secret-abc")
        # Reload the dependency since it reads the env at request time.
        from hy3dgen.api import auth as auth_module
        monkeypatch.setattr(auth_module, "get_api_key", lambda: "secret-abc")
        r = client.post("/v1/jobs", json={"type": "text_to_3d", "prompt": "x"})
        assert r.status_code == 401
        assert "X-API-Key" in r.text

    def test_wrong_key_returns_403(self, client, monkeypatch):
        from hy3dgen.api import auth as auth_module
        monkeypatch.setattr(auth_module, "get_api_key", lambda: "secret-abc")
        r = client.post(
            "/v1/jobs",
            json={"type": "text_to_3d", "prompt": "x"},
            headers={"X-API-Key": "wrong"},
        )
        assert r.status_code == 403

    def test_correct_key_passes(self, client, monkeypatch):
        from hy3dgen.api import auth as auth_module
        monkeypatch.setattr(auth_module, "get_api_key", lambda: "secret-abc")
        r = client.post(
            "/v1/jobs",
            json={"type": "text_to_3d", "prompt": "x"},
            headers={"X-API-Key": "secret-abc"},
        )
        assert r.status_code in (202, 500)
        assert r.status_code not in (401, 403)

    def test_health_remains_open(self, client, monkeypatch):
        from hy3dgen.api import auth as auth_module
        monkeypatch.setattr(auth_module, "get_api_key", lambda: "secret-abc")
        # /health is registered before the router (which has require_api_key),
        # so it must remain reachable without a key.
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        # The endpoint now returns an extended payload; the contract is
        # ``status == "ok"`` plus the readiness fields.
        assert body["status"] == "ok"
        assert "model_loaded" in body
        assert "queue_size" in body
        assert "auth_required" in body
        # When POLYFORGE_API_KEY is set (via the monkeypatch above) the
        # endpoint should reflect that.
        assert body["auth_required"] is True


class TestGetApiKey:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        from hy3dgen.api import auth as auth_module
        monkeypatch.setattr(auth_module, "get_api_key", auth_module.get_api_key.__wrapped__ if hasattr(auth_module.get_api_key, "__wrapped__") else auth_module.get_api_key)
        # Just confirm the function shape under clean env.
        import importlib
        importlib.reload(auth_module)
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        assert auth_module.get_api_key() is None

    def test_set_returns_value(self, monkeypatch):
        monkeypatch.setenv("POLYFORGE_API_KEY", "abc")
        from hy3dgen.api import auth as auth_module
        import importlib
        importlib.reload(auth_module)
        assert auth_module.get_api_key() == "abc"

    def test_blank_returns_none(self, monkeypatch):
        monkeypatch.setenv("POLYFORGE_API_KEY", "   ")
        from hy3dgen.api import auth as auth_module
        import importlib
        importlib.reload(auth_module)
        assert auth_module.get_api_key() is None


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

class TestCorsOrigins:
    def test_default_is_wildcard(self, monkeypatch):
        monkeypatch.delenv("POLYFORGE_CORS_ORIGINS", raising=False)
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        assert config_module.get_cors_origins() == ["*"]

    def test_explicit_list(self, monkeypatch):
        monkeypatch.setenv(
            "POLYFORGE_CORS_ORIGINS",
            "http://localhost:5173, http://app.example.com",
        )
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        assert config_module.get_cors_origins() == [
            "http://localhost:5173",
            "http://app.example.com",
        ]

    def test_blank_entries_are_skipped(self, monkeypatch):
        monkeypatch.setenv("POLYFORGE_CORS_ORIGINS", "http://a,,http://b,")
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        assert config_module.get_cors_origins() == ["http://a", "http://b"]


class TestBindHost:
    def test_default_is_localhost(self, monkeypatch):
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        assert config_module.get_bind_host() == "127.0.0.1"

    def test_api_key_unlocks_wildcard(self, monkeypatch):
        monkeypatch.setenv("POLYFORGE_API_KEY", "x")
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        assert config_module.get_bind_host() == "0.0.0.0"
