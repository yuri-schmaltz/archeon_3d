"""Tests for scripts/download_models.py (no network: huggingface_hub is stubbed)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "download_models.py"


@pytest.fixture
def download_models(monkeypatch):
    """Import the script with a stubbed ``huggingface_hub`` module."""
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = MagicMock(side_effect=lambda **kwargs: "/fake/cache")
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    # Drop a previous import so env-var changes take effect per test.
    sys.modules.pop("download_models", None)
    spec = importlib.util.spec_from_file_location("download_models", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["download_models"] = module
    spec.loader.exec_module(module)
    return module, hub


def _repo_ids(hub) -> list:
    return [call.kwargs["repo_id"] for call in hub.snapshot_download.call_args_list]


def test_scope_shape_downloads_shape_and_mini(download_models):
    module, hub = download_models
    assert module.main(["--scope", "shape"]) == 0
    assert _repo_ids(hub) == ["tencent/Hunyuan3D-2", "tencent/Hunyuan3D-2mini"]


def test_scope_t2i_downloads_reference_model(download_models):
    module, hub = download_models
    assert module.main(["--scope", "t2i"]) == 0
    assert _repo_ids(hub) == ["Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled"]


def test_scope_all_covers_every_model(download_models):
    module, hub = download_models
    assert module.main(["--scope", "all"]) == 0
    assert _repo_ids(hub) == [
        "tencent/Hunyuan3D-2",
        "tencent/Hunyuan3D-2mini",
        "tencent/Hunyuan3D-2mv",
        "tencent/Hunyuan3D-2",
        "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled",
    ]


def test_t2i_model_id_is_overridable(download_models, monkeypatch):
    module, hub = download_models
    monkeypatch.setenv("POLYFORGE_T2I_MODEL", "custom/t2i")
    assert module.main(["--scope", "t2i"]) == 0
    assert _repo_ids(hub) == ["custom/t2i"]


def test_shape_subfolder_restricts_patterns(download_models):
    module, hub = download_models
    assert module.main(["--scope", "multiview"]) == 0
    (kwargs,) = [call.kwargs for call in hub.snapshot_download.call_args_list]
    assert kwargs["allow_patterns"] == [
        "hunyuan3d-dit-v2-mv/*",
        "hunyuan3d-dit-v2-mv/**/*",
    ]


def test_missing_huggingface_hub_is_a_noop(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    sys.modules.pop("download_models", None)
    spec = importlib.util.spec_from_file_location("download_models", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["download_models"] = module
    spec.loader.exec_module(module)
    assert module.main(["--scope", "all"]) == 0


def test_invalid_scope_is_rejected(download_models):
    module, _ = download_models
    with pytest.raises(SystemExit) as exc:
        module.main(["--scope", "bogus"])
    assert exc.value.code == 2
