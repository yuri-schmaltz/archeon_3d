"""Real-GPU benchmark for the Archeon shape pipeline.

Usage:
    python scripts/benchmark_presets.py [--preset fast|balanced|detailed|all]

Downloads the configured model on first run (Tencent/Hunyuan3D-2mini
fits in ~5 GB and produces a low-fidelity mesh in seconds). Outputs a
JSON summary with timing, VRAM peak and face count per preset so CI
can track regressions.

The benchmark skips itself automatically when torch / diffusers /
the configured model aren't available, which keeps unit-test runs
green on machines without GPU dependencies installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

# Make ``hy3dgen`` importable when run from a checkout.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _have_torch_cuda() -> tuple[bool, str | None]:
    try:
        import torch
    except ImportError:
        return False, "torch not installed"
    if not torch.cuda.is_available():
        return False, "CUDA not available"
    return True, None


def _make_test_image(size: int = 256) -> bytes:
    """Build a tiny PNG with a colored square — enough to feed the pipeline."""
    from PIL import Image, ImageDraw
    import io

    img = Image.new("RGB", (size, size), (32, 32, 32))
    draw = ImageDraw.Draw(img)
    draw.rectangle((size // 4, size // 4, 3 * size // 4, 3 * size // 4), fill=(220, 120, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_to_base64(image_bytes: bytes) -> str:
    import base64

    return base64.b64encode(image_bytes).decode("ascii")


def _format_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TiB"


def benchmark_one(worker, image_b64: str, steps: int, octree_resolution: int, save_dir: Path, *, uid: str) -> dict:
    """Run a single benchmark and return timing + VRAM info."""
    import torch

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    params = {
        "type": "image_to_3d",
        "image": image_b64,
        "seed": 1234,
        "steps": steps,
        "guidance": 5.0,
        "octree_resolution": octree_resolution,
        # Use 'mc' as the marching cubes algo so the benchmark doesn't
        # require the optional `diso` package (DMC depends on CUDA
        # extensions that may not be available on every host).
        "mc_algo": "mc",
    }
    file_path = worker.generate(uid, params, str(save_dir))
    elapsed = time.monotonic() - started
    peak_mem = torch.cuda.max_memory_allocated()
    file_size = Path(file_path).stat().st_size if Path(file_path).exists() else 0
    face_count = 0
    try:
        import trimesh
        mesh = trimesh.load(file_path, force="mesh")
        face_count = int(len(mesh.faces))
    except Exception:
        pass
    return {
        "steps": steps,
        "octree_resolution": octree_resolution,
        "elapsed_s": round(elapsed, 3),
        "peak_vram_mb": round(peak_mem / 1024 / 1024, 1) if peak_mem else None,
        "output_size": _format_bytes(file_size),
        "face_count": face_count,
        "file_path": file_path,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=("fast", "balanced", "detailed", "all"),
        default="all",
        help="Which preset(s) to benchmark.",
    )
    parser.add_argument(
        "--device",
        default="cuda" if _have_torch_cuda()[0] else "cpu",
        help="Device to load the model on.",
    )
    parser.add_argument(
        "--save-dir",
        default=str(Path(os.environ.get("ARCHEON_SAVE_DIR", "/tmp/archeon_bench"))),
        help="Where to write benchmark outputs.",
    )
    parser.add_argument(
        "--model-path",
        default="tencent/Hunyuan3D-2mini",
        help="HF model id (mini = fast, full = slower + larger).",
    )
    parser.add_argument(
        "--model-subfolder",
        default="hunyuan3d-dit-v2-mini-turbo",
        help="HF subfolder for the model.",
    )
    args = parser.parse_args(argv)

    available, reason = _have_torch_cuda()
    if not available and args.device.startswith("cuda"):
        print(json.dumps({"skipped": True, "reason": reason}, indent=2))
        return 0  # Skip cleanly rather than fail CI.

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    presets = {
        "fast": {"steps": 5, "octree_resolution": 192},
        "balanced": {"steps": 50, "octree_resolution": 256},
        "detailed": {"steps": 100, "octree_resolution": 384},
    }
    selected = (
        list(presets.values())
        if args.preset == "all"
        else [presets[args.preset]]
    )

    print(f"[benchmark] device={args.device} model={args.model_path}/{args.model_subfolder}")

    # Lazy-import to avoid loading torch/diffusers when the device is unavailable.
    from hy3dgen.inference import ModelWorker

    worker = ModelWorker(
        model_path=args.model_path,
        subfolder=args.model_subfolder,
        device=args.device,
    )

    image_b64 = _image_to_base64(_make_test_image())
    results: list[dict] = []
    for index, preset in enumerate(selected):
        uid = f"bench-{int(time.time())}-{index}"
        print(f"[benchmark] preset steps={preset['steps']} octree={preset['octree_resolution']}")
        result = benchmark_one(worker, image_b64, preset["steps"], preset["octree_resolution"], save_dir, uid=uid)
        print(
            f"  elapsed={result['elapsed_s']}s "
            f"vram={result['peak_vram_mb']}MB "
            f"output={result['output_size']} "
            f"faces={result['face_count']}"
        )
        results.append(result)

    summary = {
        "skipped": False,
        "device": args.device,
        "model": f"{args.model_path}/{args.model_subfolder}",
        "platform": platform.platform(),
        "results": results,
    }
    out_file = save_dir / "benchmark.json"
    out_file.write_text(json.dumps(summary, indent=2))
    print(f"[benchmark] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))