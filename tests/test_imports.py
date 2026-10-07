"""
Smoke tests for Hunyuan3D-2GP.
Tests that all critical modules can be imported and basic classes exist.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assert_in_isolated_process(statement: str) -> None:
    """Import heavy ML modules in a fresh interpreter.

    Several texture/shape modules manipulate native extension state in ways
    that do not survive being imported twice in one pytest process. Running
    each smoke import in a subprocess keeps these tests hermetic and lets the
    full suite run without import-order coupling.
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


def test_hy3dgen_import():
    """Test that the core hy3dgen package imports without error."""
    _assert_in_isolated_process("import hy3dgen; assert hasattr(hy3dgen, '__file__')")


def test_shapegen_imports():
    """Test shapegen module imports and key classes exist."""
    _assert_in_isolated_process(
        "from hy3dgen.shapegen import ("
        "Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover, "
        "DegenerateFaceRemover, FaceReducer, MeshSimplifier);"
        "assert Hunyuan3DDiTFlowMatchingPipeline is not None;"
        "assert FloaterRemover is not None;"
        "assert DegenerateFaceRemover is not None;"
        "assert FaceReducer is not None;"
        "assert MeshSimplifier is not None"
    )


def test_shapegen_pipelines_module():
    """Test that shapegen.pipelines and export_to_trimesh exist."""
    _assert_in_isolated_process(
        "from hy3dgen.shapegen.pipelines import export_to_trimesh;"
        "assert callable(export_to_trimesh)"
    )


def test_rembg_import():
    """Test background remover imports."""
    _assert_in_isolated_process(
        "from hy3dgen.rembg import BackgroundRemover;assert BackgroundRemover is not None"
    )


def test_text2image_import():
    """Test text2image module imports."""
    _assert_in_isolated_process(
        "from hy3dgen.text2image import HunyuanDiTPipeline;assert HunyuanDiTPipeline is not None"
    )


def test_shapegen_utils():
    """Test that shapegen utils and logger exist."""
    _assert_in_isolated_process(
        "from hy3dgen.shapegen.utils import logger; assert logger is not None"
    )


def test_postprocessors_are_callable():
    """Test that postprocessor classes can be instantiated."""
    _assert_in_isolated_process(
        "from hy3dgen.shapegen import ("
        "FloaterRemover, DegenerateFaceRemover, FaceReducer);"
        "assert callable(FloaterRemover());"
        "assert callable(DegenerateFaceRemover());"
        "assert callable(FaceReducer())"
    )
