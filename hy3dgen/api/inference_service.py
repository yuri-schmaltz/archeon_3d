"""Shared inference service.

The previous design tied ``ModelWorker`` directly to the
``PriorityRequestManager``. The Gradio ``launcher.py`` created its
own globals (``i23d_worker``, ``texgen_worker``...), leading to
two code paths that drifted over time.

``InferenceService`` is the single source of truth. Both the API
manager and the launcher can construct one and ask it to load /
dispatch jobs. The service is responsible for:

  - Lifecycle (``start``/``stop``).
  - Lazy model loading with a single shape pipeline at a time
    (single-tenant VRAM budget).
  - Submission through a queue (``submit``) and stream of
    ``InferenceEvent`` notifications (``subscribe``).
  - Mode introspection for ``/v1/capabilities`` and the launcher's
    own status panel.

The existing ``PriorityRequestManager`` is now an HTTP-shaped
adapter that delegates to an ``InferenceService`` instance, so
existing tests for the manager continue to work unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JobStage(str, Enum):
    QUEUED = "queued"
    LOADING_MODEL = "loading_model"
    SHAPE_GENERATION = "shape_generation"
    TEXTURE = "texture"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class InferenceEvent:
    """A status change emitted by the service to all listeners."""

    uid: str
    stage: JobStage
    progress: float | None = None
    error: str | None = None
    file_path: str | None = None
    request_type: str = "unknown"
    at: float = field(default_factory=time.time)


@dataclass
class InferenceJob:
    """Service-level representation of a queued job."""

    uid: str
    params: dict[str, Any]
    save_dir: str
    request_type: str = "unknown"
    created_at: float = field(default_factory=time.time)


class InferenceCancelledError(Exception):
    """Raised inside the worker when the service has been asked to stop."""


_DEFAULT_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {"steps": 5, "guidance": 5.0, "octree_resolution": 192},
    "balanced": {"steps": 50, "guidance": 5.0, "octree_resolution": 256},
    "detailed": {"steps": 100, "guidance": 7.5, "octree_resolution": 384},
}


def _load_calibrated_presets() -> dict[str, dict[str, Any]]:
    """Load the preset table from the calibration JSON if present.

    The calibration JSON lives at ``docs/archeon/benchmarks/calibration.json``
    or ``/tmp/archeon_bench/benchmark.json``. Missing keys fall back to
    the documented defaults so a build with no benchmark artifact
    keeps working unchanged.
    """
    candidates = [
        Path("docs/archeon/benchmarks/calibration.json"),
        Path("/tmp/archeon_bench/benchmark.json"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if data.get("skipped"):
            continue
        device = data.get("device", "unknown")
        measured: dict[tuple[int, int], dict[str, Any]] = {}
        for result in data.get("results", []):
            key = (int(result.get("steps", 0)), int(result.get("octree_resolution", 0)))
            measured[key] = result
        enriched = {name: dict(preset) for name, preset in _DEFAULT_PRESETS.items()}
        for name, preset in _DEFAULT_PRESETS.items():
            match = measured.get((preset["steps"], preset["octree_resolution"]))
            if match is None:
                continue
            enriched[name] = {
                **preset,
                "expected_elapsed_s": match.get("elapsed_s"),
                "expected_vram_mb": match.get("peak_vram_mb"),
                "calibrated_on": device,
            }
        return enriched
    return {name: dict(preset) for name, preset in _DEFAULT_PRESETS.items()}


class InferenceService:
    """Single-tenant queue + worker for 3D inference jobs.

    Use ``start()`` once at app boot, then call ``submit(job)`` for
    each new request. The service guarantees serial execution (no
    two jobs run concurrently) and surfaces every state transition
    via ``subscribe()`` so the HTTP layer can mirror it onto SSE.
    """

    def __init__(
        self,
        device: str = "cuda",
        *,
        save_dir: str | None = None,
        model_path: str = "tencent/Hunyuan3D-2mini",
        model_subfolder: str = "hunyuan3d-dit-v2-mini-turbo",
        multiview_model: str = "tencent/Hunyuan3D-2mv",
        multiview_subfolder: str = "hunyuan3d-dit-v2-mv",
    ) -> None:
        self.device = device
        self.save_dir = save_dir
        self.model_path = model_path
        self.model_subfolder = model_subfolder
        self.multiview_model = multiview_model
        self.multiview_subfolder = multiview_subfolder

        self._queue: asyncio.Queue[InferenceJob | None] = asyncio.Queue()
        self._worker: Any = None  # ModelWorker, lazily imported
        self._worker_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        self._jobs: dict[str, InferenceJob] = {}
        self._subscribers: list[asyncio.Queue[InferenceEvent]] = []
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the background worker. Idempotent."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run(), name="inference-service")
            logger.info("InferenceService worker started.")

    async def stop(self) -> None:
        """Cancel any in-flight job and stop the worker task."""
        self._shutdown.set()
        # Sentinel to unblock the queue.get() inside _run().
        await self._queue.put(None)
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
        logger.info("InferenceService worker stopped.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, params: dict[str, Any], save_dir: str | None = None) -> InferenceJob:
        """Enqueue a new job and return its descriptor."""
        if self.shutdown.is_set():
            raise RuntimeError("InferenceService has been stopped.")
        uid = params.get("uid") or uuid.uuid4().hex
        params = dict(params)
        params["uid"] = uid
        request_type = params.get("type", "unknown")
        target_dir = save_dir or self.save_dir
        if target_dir is None:
            raise ValueError("save_dir is required (either per-submit or at construction time).")
        job = InferenceJob(
            uid=uid,
            params=params,
            save_dir=target_dir,
            request_type=request_type,
        )
        self._jobs[uid] = job
        await self._queue.put(job)
        self._publish(
            InferenceEvent(
                uid=uid,
                stage=JobStage.QUEUED,
                request_type=request_type,
            )
        )
        return job

    async def cancel(self, uid: str) -> bool:
        """Best-effort cancel. Returns True if the job was queued and
        marked cancelled, False if it was already processing/missing.

        Processing jobs are not interruptible (the underlying pipeline
        is a single blocking call). The caller should drain and
        reconcile once the job naturally completes.
        """
        async with self._lock:
            job = self._jobs.get(uid)
            if job is None:
                return False
            self._publish(
                InferenceEvent(
                    uid=uid,
                    stage=JobStage.CANCELLED,
                    request_type=job.request_type,
                )
            )
            self._jobs.pop(uid, None)
            return True

    async def warmup(self) -> str:
        """Eagerly load the inference model into the worker.

        Returns one of:
          - ``"already_loaded"`` when ``ModelWorker.pipeline`` is set.
          - ``"loading"`` when a new load was scheduled.
          - ``"failed"`` if the load raised synchronously.

        Note: building the ``ModelWorker`` instance itself is cheap
        (it just stores config). The actual weight download + load
        happens inside ``worker.warmup()``, which we run in a thread
        so the event loop stays responsive.
        """
        from hy3dgen.inference import ModelWorker

        if self._worker is not None and getattr(self._worker, "pipeline", None) is not None:
            return "already_loaded"
        try:
            if self._worker is None:
                self._worker = await asyncio.to_thread(
                    ModelWorker,
                    device=self.device,
                    model_path=self.model_path,
                    subfolder=self.model_subfolder,
                    multiview_model_path=self.multiview_model,
                    multiview_subfolder=self.multiview_subfolder,
                    enable_tex=True,
                    enable_t2i=True,
                )
            # Force the actual weight download + load so /models/status
            # flips to ``loaded=true`` once done.
            await asyncio.to_thread(self._worker.warmup)
        except Exception as exc:
            self.last_error = f"warmup failed: {exc}"
            logger.exception("InferenceService warmup failed")
            return "failed"
        return "loading"

    def subscribe(self) -> asyncio.Queue[InferenceEvent]:
        """Register a listener. The returned queue receives every event."""
        q: asyncio.Queue[InferenceEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[InferenceEvent]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(queue)

    @property
    def jobs(self) -> dict[str, InferenceJob]:
        """Snapshot of currently-tracked jobs (read-only)."""
        return dict(self._jobs)

    @property
    def shutdown(self) -> asyncio.Event:
        return self._shutdown

    def capabilities(self) -> dict[str, Any]:
        """Static + dynamic state snapshot for ``/v1/capabilities``.

        The shape mirrors what the manager used to return so HTTP
        callers don't see a difference. ``models[*].loaded`` reflects
        the live state of the worker (None until the first job runs).

        The preset table is augmented with **measured** timings when
        a calibration JSON is present (see ``scripts/benchmark_presets.py``).
        This lets the UI show "≈ 30 s on RTX 3060" instead of a vague
        "fast" label.
        """
        worker = self._worker
        shape_loaded = worker is not None and getattr(worker, "pipeline", None) is not None
        tex_loaded = worker is not None and getattr(worker, "pipeline_tex", None) is not None
        t2i_loaded = worker is not None and getattr(worker, "pipeline_t2i", None) is not None
        mv_loaded = worker is not None and getattr(worker, "_shape_mode", None) == "multiview"
        return {
            "modes": {
                "text": {
                    "available": bool(t2i_loaded or shape_loaded),
                    "reason": None if (t2i_loaded or shape_loaded) else "Shape/text-to-image model not loaded.",
                    "requires": ["text_to_image"] if not t2i_loaded else [],
                },
                "image": {
                    "available": bool(shape_loaded),
                    "reason": None if shape_loaded else "Shape model not loaded.",
                    "requires": [],
                },
                "multiview": {
                    "available": bool(mv_loaded or shape_loaded),
                    "reason": None if (mv_loaded or shape_loaded) else "Multiview model not loaded.",
                    "requires": [],
                },
                "texture": {
                    "available": bool(tex_loaded or shape_loaded),
                    "reason": None if (tex_loaded or shape_loaded) else "Texture model not loaded.",
                    "requires": [],
                },
            },
            "models": {
                "shape": {"id": self.model_path, "subfolder": self.model_subfolder, "loaded": shape_loaded},
                "multiview": {"id": self.multiview_model, "subfolder": self.multiview_subfolder, "loaded": mv_loaded},
                "texture": {"id": self.model_path, "subfolder": None, "loaded": tex_loaded},
                "text_to_image": {"id": self.model_path, "subfolder": None, "loaded": t2i_loaded},
            },
            "presets": _load_calibrated_presets(),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _publish(self, event: InferenceEvent) -> None:
        """Fan out an event to all subscribers."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - we don't bound the queue
                continue

    async def _run(self) -> None:
        """Worker loop. Pulls jobs and dispatches them serially."""
        while not self._shutdown.is_set():
            job = await self._queue.get()
            if job is None:
                break
            try:
                await self._execute(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("InferenceService worker error on uid=%s", job.uid)
                self.last_error = str(exc)
                self._publish(
                    InferenceEvent(
                        uid=job.uid,
                        stage=JobStage.FAILED,
                        error=str(exc),
                        request_type=job.request_type,
                    )
                )
            finally:
                self._jobs.pop(job.uid, None)
                self._queue.task_done()

    async def _execute(self, job: InferenceJob) -> None:
        """Run a single job, publishing stage events along the way."""
        # Lazy import keeps ``hy3dgen[api]`` installable without ML deps.
        from hy3dgen.inference import ModelWorker

        if self._worker is None:
            self._publish(
                InferenceEvent(
                    uid=job.uid,
                    stage=JobStage.LOADING_MODEL,
                    progress=0.05,
                    request_type=job.request_type,
                )
            )
            self._worker = await asyncio.to_thread(
                ModelWorker,
                device=self.device,
                model_path=self.model_path,
                subfolder=self.model_subfolder,
                multiview_model_path=self.multiview_model,
                multiview_subfolder=self.multiview_subfolder,
                enable_tex=True,
                enable_t2i=True,
            )
            self._publish(
                InferenceEvent(
                    uid=job.uid,
                    stage=JobStage.LOADING_MODEL,
                    progress=0.3,
                    request_type=job.request_type,
                )
            )

        params = dict(job.params)
        # ModelWorker expects params to be in its native dict shape.
        # The manager does this remapping; reproduce the same here.
        if params.get("type") == "text_to_3d" and "prompt" in params and "text" not in params:
            params["text"] = params["prompt"]
        if params.get("type") == "texture_mesh":
            params["texture"] = True
            if params.get("prompt") and "text" not in params:
                params["text"] = params["prompt"]

        self._publish(
            InferenceEvent(
                uid=job.uid,
                stage=JobStage.SHAPE_GENERATION,
                progress=0.4,
                request_type=job.request_type,
            )
        )

        if self._shutdown.is_set():
            raise InferenceCancelledError("Service shutting down")

        # Heavy lifting in a thread.
        file_path = await asyncio.to_thread(
            self._worker.generate,
            job.uid,
            params,
            job.save_dir,
        )

        self._publish(
            InferenceEvent(
                uid=job.uid,
                stage=JobStage.EXPORTING,
                progress=0.95,
                request_type=job.request_type,
            )
        )

        self.last_error = None
        self._publish(
            InferenceEvent(
                uid=job.uid,
                stage=JobStage.COMPLETED,
                progress=1.0,
                file_path=file_path,
                request_type=job.request_type,
            )
        )


# Type alias for callers that want to inject a no-op service in tests.
InferenceFactory = Callable[[], Awaitable[InferenceService]]
