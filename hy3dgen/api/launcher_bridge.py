"""Bridge between the Gradio launcher and the shared InferenceService.

The original ``launcher.py`` built its own globals (one per pipeline)
and the API built its own ``PriorityRequestManager``-level worker. The
two code paths drifted over time. Now there's a single source of
truth — ``InferenceService`` — and this bridge lets the launcher
hook into it without forcing a full rewrite of the Gradio UI.

Use it like:

    from hy3dgen.api.launcher_bridge import get_shared_service

    service = await get_shared_service(args)
    job = await service.submit({"type": "image_to_3d", "image": "..."}, save_dir=...)

The launcher can still keep its legacy globals for the parts of the
UI that haven't been migrated; the bridge is opt-in.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hy3dgen.api.inference_service import InferenceService

logger = logging.getLogger(__name__)

__all__ = ["ensure_service_started", "get_shared_service"]

_singleton: InferenceService | None = None
_singleton_lock = asyncio.Lock()


def _build_from_args(args: Any) -> InferenceService:
    """Translate ``launcher.py`` argparse Namespace into a service config."""
    from hy3dgen.api.inference_service import InferenceService

    return InferenceService(
        device=getattr(args, "device", "cuda"),
        save_dir=getattr(args, "save_dir", "./output"),
        model_path=getattr(args, "model_path", "tencent/Hunyuan3D-2mini"),
        model_subfolder=getattr(args, "subfolder", "hunyuan3d-dit-v2-mini-turbo"),
        multiview_model=getattr(args, "mv_model_path", "tencent/Hunyuan3D-2mv"),
        multiview_subfolder=getattr(args, "mv_subfolder", "hunyuan3d-dit-v2-mv"),
    )


async def get_shared_service(args: Any) -> InferenceService:
    """Return (and lazily start) the singleton InferenceService.

    The instance is built from the launcher's argparse Namespace so
    that CLI flags (``--device``, ``--model_path``, ``--save_dir``)
    keep their existing semantics. Re-invoking this function returns
    the same service, which means the launcher and the API (if
    co-hosted) share the underlying ``ModelWorker``.
    """
    global _singleton
    async with _singleton_lock:
        if _singleton is None:
            _singleton = _build_from_args(args)
            await _singleton.start()
            logger.info("Shared InferenceService constructed from launcher args.")
        return _singleton


async def ensure_service_started() -> InferenceService | None:
    """Best-effort helper for tests / scripts: ensure the singleton exists."""
    if _singleton is not None:
        return _singleton
    return None


def reset_singleton() -> None:
    """Clear the singleton. Only used by tests."""
    global _singleton
    _singleton = None
