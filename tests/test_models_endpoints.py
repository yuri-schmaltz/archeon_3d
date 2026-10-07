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

        self.worker = SimpleNamespace(
            pipeline=object(),
            pipeline_t2i=object(),
            t2i_model_path="custom/t2i",
        )


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
    assert body["text_to_image_loaded"] is False
    assert body["text_to_image_model"] == "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled"
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
    assert body["text_to_image_loaded"] is True
    assert body["text_to_image_model"] == "custom/t2i"


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

    # Patch the globals actually used by the bound ``warmup_model``
    # implementation. Reloading ``hy3dgen.api.manager`` elsewhere in the
    # suite can leave this stub subclass bound to an older module object.
    warmup_globals = type(stubbed_manager).warmup_model.__globals__
    monkeypatch.setitem(warmup_globals, "ModelWorker", _boom)
    # Run on a fresh thread: ``warmup_model`` takes the threaded fallback
    # only when the calling thread has no running event loop, which the
    # full suite cannot guarantee on the main pytest thread.
    import threading
    import time

    outcome: dict = {}

    def _warmup() -> None:
        try:
            outcome["status"] = stubbed_manager.warmup_model()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_warmup)
    thread.start()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    for _ in range(50):
        if stubbed_manager.last_error:
            break
        time.sleep(0.1)
    assert outcome.get("status") == "queued"
    assert stubbed_manager.last_error is not None
    assert "warmup failed" in stubbed_manager.last_error
