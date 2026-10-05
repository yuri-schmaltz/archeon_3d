"""Pre-download the Archeon inference models.

Useful for users who want to populate the HF cache ahead of time
(e.g. on a slow connection, or to warm a container image). The
default Archeon config loads models lazily on the first job; this
script does the download step in isolation without spinning up the
shape pipeline.

Usage:
    python scripts/download_models.py [--scope shape|multiview|tex|all] [--device cpu|cuda]

Environment variables:
    ARCHEON_MODEL              (default: tencent/Hunyuan3D-2)
    ARCHEON_MODEL_SUBFOLDER    (default: hunyuan3d-dit-v2-0)
    ARCHEON_MULTIVIEW_MODEL    (default: tencent/Hunyuan3D-2mv)
    ARCHEON_MULTIVIEW_SUBFOLDER (default: hunyuan3d-dit-v2-mv)
    ARCHEON_TEX_MODEL_PATH     (default: tencent/Hunyuan3D-2)
    ARCHEON_MINI_MODEL         (default: tencent/Hunyuan3D-2mini)

The script is a no-op if ``torch`` / ``huggingface_hub`` aren't
installed, so it stays safe to ship in the repo.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _have_huggingface_hub() -> tuple[bool, str | None]:
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        return False, "huggingface_hub is not installed"
    return True, None


def _snapshot(model_id: str, subfolder: str | None) -> None:
    """Download a single model + optional subfolder.

    Mirrors what ``from_pretrained`` does at runtime, but without
    loading weights into PyTorch (faster, less RAM).
    """
    from huggingface_hub import snapshot_download

    kwargs: dict = {"repo_id": model_id, "allow_patterns": None}
    if subfolder:
        # Restrict to the subfolder to avoid pulling checkpoints for
        # other configurations we don't use.
        kwargs["allow_patterns"] = [f"{subfolder}/*", f"{subfolder}/**/*"]
    print(f"[download] {model_id}" + (f" / {subfolder}" if subfolder else ""))
    path = snapshot_download(**kwargs)
    print(f"[download]   -> {path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=("shape", "multiview", "tex", "all"),
        default="all",
        help="Which models to download. ``all`` covers the four models the API may use.",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("ARCHEON_DEVICE", "cuda"),
        help="Device hint (informational; weights aren't loaded here).",
    )
    args = parser.parse_args(argv)

    ok, reason = _have_huggingface_hub()
    if not ok:
        print(f"[skip] {reason}. Run ``./launcher.sh`` first to install it.")
        return 0

    print(f"[info] device hint: {args.device} (weights are downloaded but not loaded)")

    shape_model = os.environ.get("ARCHEON_MODEL", "tencent/Hunyuan3D-2")
    shape_sub = os.environ.get("ARCHEON_MODEL_SUBFOLDER", "hunyuan3d-dit-v2-0")
    mv_model = os.environ.get("ARCHEON_MULTIVIEW_MODEL", "tencent/Hunyuan3D-2mv")
    mv_sub = os.environ.get("ARCHEON_MULTIVIEW_SUBFOLDER", "hunyuan3d-dit-v2-mv")
    tex_model = os.environ.get("ARCHEON_TEX_MODEL_PATH", "tencent/Hunyuan3D-2")
    mini_model = os.environ.get("ARCHEON_MINI_MODEL", "tencent/Hunyuan3D-2mini")

    if args.scope in ("shape", "all"):
        _snapshot(shape_model, shape_sub)
        _snapshot(mini_model, "hunyuan3d-dit-v2-mini-turbo")
    if args.scope in ("multiview", "all"):
        _snapshot(mv_model, mv_sub)
    if args.scope in ("tex", "all"):
        # Texture pipeline uses the main model; download its subfolder
        # under the same repo (no separate subfolder needed).
        _snapshot(tex_model, None)

    print("[done] All requested models are in the HF cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))