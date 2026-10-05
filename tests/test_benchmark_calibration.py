"""Calibrate the shape preset table from real GPU measurements.

Reads the JSON output produced by ``scripts/benchmark_presets.py``
and asserts that the documented presets actually match the timings
we observed on real hardware. CI runs this with the fast preset only
to keep the budget small; the full sweep is run on a developer
machine and the resulting JSON is committed to
``docs/archeon/benchmarks/calibration_<device>.json``.

The test skips automatically when no benchmark file is present
(no GPU in CI).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATHS = [
    REPO_ROOT / "docs" / "archeon" / "benchmarks" / "calibration.json",
    Path("/tmp/archeon_bench/benchmark.json"),
]

EXPECTED = {
    "fast": {"steps": 5, "octree_resolution": 192, "max_seconds": 90},
    "balanced": {"steps": 50, "octree_resolution": 256, "max_seconds": 180},
    "detailed": {"steps": 100, "octree_resolution": 384, "max_seconds": 300},
}


def _load_benchmark() -> dict | None:
    for path in BENCHMARK_PATHS:
        if path.exists():
            return json.loads(path.read_text())
    return None


def test_benchmark_record_matches_presets() -> None:
    bench = _load_benchmark()
    if bench is None:
        pytest.skip("No benchmark.json available (GPU not present in this environment).")
    if bench.get("skipped"):
        pytest.skip(f"Benchmark was skipped: {bench.get('reason')}")
    results = bench["results"]
    assert results, "Benchmark produced no results"
    # Map by steps to support running individual presets.
    by_steps = {result["steps"]: result for result in results}
    for preset_name, expected in EXPECTED.items():
        result = by_steps.get(expected["steps"])
        if result is None:
            continue
        assert result["octree_resolution"] == expected["octree_resolution"], (
            f"Preset {preset_name} octree mismatch"
        )
        # Soft upper-bound on runtime. Generous threshold to avoid CI
        # flakes; the docs file documents the actual median.
        assert result["elapsed_s"] <= expected["max_seconds"], (
            f"Preset {preset_name} took {result['elapsed_s']}s > {expected['max_seconds']}s"
        )
        assert result["peak_vram_mb"] is None or result["peak_vram_mb"] > 0


def test_benchmark_record_has_required_keys() -> None:
    bench = _load_benchmark()
    if bench is None:
        pytest.skip("No benchmark.json available")
    if bench.get("skipped"):
        pytest.skip(f"Benchmark was skipped: {bench.get('reason')}")
    required = {"device", "model", "platform", "results"}
    assert required.issubset(bench)
    for result in bench["results"]:
        for key in ("steps", "octree_resolution", "elapsed_s", "output_size"):
            assert key in result, f"Missing key {key} in {result}"
