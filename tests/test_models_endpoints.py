"""Tests for /v1/models/load + /v1/models/status."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hy3dgen.api import server as server_module
from hy3dgen.api.deps import get_manager
from hy3dgen.api.manager import PriorityRequestManager


class _StubManager(PriorityRequestManager):
    """Manager that lets us toggle the worker on demand without
    hitting the real ModelWorker (which would try to download GBs)."""

    def __init__(self) -> None:
        super().__init__(device="cpu", store=None)
        self._stub_loaded = False

    def _attach_stub(self) -> None:
        """Attach a fake worker object whose ``.pipeline`` is non-None."""
        from types import SimpleNamespace

        self.worker = SimpleNamespace(pipeline=object())


@pytest.fixture
def stubbed_manager(monkeypatch: pytest.MonkeyPatch):
    stub = _StubManager()
    app = server_module.app
    app.dependency_overrides[get_manager] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_manager, None)


def test_status_reports_not_loaded(stubbed_manager: _StubManager) -> None:
    client = TestClient(server_module.app)
    resp = client.get("/v1/models/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded"] is False
    assert body["model"]
    assert body["device"] == "cpu"


def test_status_reports_loaded_after_worker_attached(
    stubbed_manager: _StubManager,
) -> None:
    stubbed_manager._attach_stub()
    client = TestClient(server_module.app)
    resp = client.get("/v1/models/status")
    body = resp.json()
    assert body["loaded"] is True


def test_load_returns_already_loaded_when_worker_present(
    stubbed_manager: _StubManager,
) -> None:
    stubbed_manager._attach_stub()
    client = TestClient(server_module.app)
    resp = client.post("/v1/models/load")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "already_loaded"
    assert body["model"]


def test_load_schedules_when_worker_missing(stubbed_manager: _StubManager) -> None:
    """When no worker is attached, POST /models/load must return 200
    with status="loading" and *not* block the event loop."""
    client = TestClient(server_module.app)
    resp = client.post("/v1/models/load")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"loading", "queued"}
    assert body["model"]


def test_load_handles_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch, stubbed_manager: _StubManager
) -> None:
    """If the load raises synchronously, the manager must record
    the error in ``last_error`` instead of letting it bubble up."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated disk full")

    # Simulate that the no-loop branch is used by calling warmup_model
    # in a thread; verify last_error is populated.

    monkeypatch.setattr(
        "hy3dgen.inference.ModelWorker",
        _boom,
    )
    # The ``loop`` path won't fire here (we're inside TestClient
    # which has no running loop on the same thread); so warmup_model
    # will use the threaded fallback. Wait briefly for the thread
    # to set last_error.
    stubbed_manager.warmup_model()
    import time

    for _ in range(20):
        if stubbed_manager.last_error:
            break
        time.sleep(0.05)
    assert stubbed_manager.last_error is not None
    assert "warmup failed" in stubbed_manager.last_error
