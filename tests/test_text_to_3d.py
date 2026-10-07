"""Regression tests for the text_to_3d reference-image stage."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from hy3dgen.inference import (
    DEFAULT_T2I_MODEL,
    ModelWorker,
    model_capability_snapshot,
    worker_model_state,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assert_in_isolated_process(statement: str) -> None:
    """Run Dumbo text-to-image checks without importing diffusers/torch here.

    The texture-loading tests leave torch extension state that cannot safely
    import the T2I stack a second time in the same pytest process.
    """
    completed = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_t2i_model_id_is_shared():
    _assert_in_isolated_process(
        "from hy3dgen.inference import DEFAULT_T2I_MODEL;"
        "from hy3dgen.text2image import T2I_MODEL_ID;"
        "assert T2I_MODEL_ID == DEFAULT_T2I_MODEL == ("
        "'Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled')"
    )


def test_t5_tokenizer_is_not_a_placeholder():
    """Guard the sentencepiece dependency: without it transformers exposes
    ``T5Tokenizer`` as a Placeholder and diffusers cannot load HunyuanDiT."""

    _assert_in_isolated_process(
        "from transformers import T5Tokenizer;"
        "assert type(T5Tokenizer).__name__ != 'Placeholder';"
        "assert 'dummy' not in type(T5Tokenizer).__module__"
    )


def test_t2i_call_uses_pipeline_device_and_prompt_prefix():
    _assert_in_isolated_process(
        "import torch;"
        "from hy3dgen.text2image import HunyuanDiTPipeline, MAX_PROMPT_CHARS;"
        "devices = [];\n"
        "class FakeGenerator:\n"
        "    def __init__(self, device=None):\n"
        "        devices.append(device)\n"
        "    def manual_seed(self, seed):\n"
        "        self.seed = seed\n"
        "        return self\n"
        "torch.Generator = FakeGenerator;"
        "expected_image = object();"
        "calls = [];\n"
        "class FakePipe:\n"
        "    device = torch.device('cpu')\n"
        "    def __call__(self, **kwargs):\n"
        "        calls.append(kwargs)\n"
        "        return [[expected_image]]\n"
        "pipeline = HunyuanDiTPipeline.__new__(HunyuanDiTPipeline);"
        "pipeline.pipe = FakePipe();"
        "pipeline.pos_txt = ' POS';"
        "pipeline.neg_txt = ' NEG';"
        "result = pipeline('x' * 100, seed=3);"
        "assert result is expected_image;"
        "assert calls[0]['prompt'] == 'x' * MAX_PROMPT_CHARS + ' POS';"
        "assert calls[0]['negative_prompt'] == ' NEG';"
        "assert devices == [torch.device('cpu')]"
    )


def _install_fake_t2i(monkeypatch, calls: dict):
    """Provide a fake ``hy3dgen.text2image`` module without importing diffusers."""

    class _FakeT2I:
        def __init__(self, model_path, device=None) -> None:
            calls["model_path"] = model_path
            calls["device"] = device

        def __call__(self, prompt, seed=0):
            calls["prompt"] = prompt
            calls["seed"] = seed
            return "reference-image"

    module = types.ModuleType("hy3dgen.text2image")
    module.HunyuanDiTPipeline = _FakeT2I
    monkeypatch.setitem(sys.modules, "hy3dgen.text2image", module)


def test_image_from_text_passes_model_and_seed(monkeypatch):
    calls: dict = {}
    _install_fake_t2i(monkeypatch, calls)
    worker = ModelWorker(enable_t2i=True, t2i_model_path="custom/t2i")

    assert worker._image_from_text("a prompt", seed=7) == "reference-image"
    assert calls == {
        "model_path": "custom/t2i",
        "device": worker.device,
        "prompt": "a prompt",
        "seed": 7,
    }


def test_generate_passes_request_seed_to_reference_image(monkeypatch, tmp_path):
    calls: dict = {}

    def _fake_image_from_text(self, prompt, seed=0):
        calls["prompt"] = prompt
        calls["seed"] = seed
        return "reference-image"

    class _FakeMesh:
        def export(self, path) -> None:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("mesh")

    fake_trimesh = SimpleNamespace(load=lambda *args, **kwargs: _FakeMesh())
    monkeypatch.setattr(ModelWorker, "_image_from_text", _fake_image_from_text)
    monkeypatch.setitem(sys.modules, "trimesh", fake_trimesh)
    worker = ModelWorker(enable_t2i=True)

    mesh_payload = base64.b64encode(b"fake-glb").decode("ascii")
    saved = worker._generate(
        "uid-1",
        {
            "type": "text_to_3d",
            "text": "a prompt",
            "mesh": mesh_payload,
            "seed": 7,
            "remove_background": False,
            "format": "glb",
        },
        str(tmp_path),
    )

    assert calls == {"prompt": "a prompt", "seed": 7}
    assert saved.endswith("uid-1.glb")


def test_capabilities_use_actual_t2i_model_and_enablement():
    worker = ModelWorker(enable_t2i=True)
    worker.pipeline = object()
    snapshot = model_capability_snapshot(worker_model_state(worker))

    assert snapshot["models"]["text_to_image"]["id"] == DEFAULT_T2I_MODEL
    assert snapshot["modes"]["text"]["available"] is True

    worker.enable_t2i = False
    snapshot = model_capability_snapshot(worker_model_state(worker))
    assert snapshot["modes"]["text"]["available"] is False
