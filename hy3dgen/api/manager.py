import asyncio
import contextlib
import gc
import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING

from hy3dgen.api.metrics import (
    JOB_DURATION,
    JOBS_COMPLETED,
    JOBS_FAILED,
    JOBS_IN_MEMORY,
    JOBS_SUBMITTED,
    end_span,
    start_span,
)
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import GenerationRequest, JobRequest, JobResponse, JobStatus
from hy3dgen.api.timeutils import timestamp, utc_now
from hy3dgen.inference import ModelWorker
from hy3dgen.version import __version__

if TYPE_CHECKING:
    from hy3dgen.api.inference_service import InferenceEvent, InferenceService

logger = logging.getLogger(__name__)


def _status_transition(job: "JobResponse", expected: "JobStatus", new: "JobStatus") -> bool:
    """Atomically set ``job.status = new`` only if the current status is
    ``expected``. Returns True if the transition happened, False if the
    status had already changed (caller should treat as a no-op race).

    This is the manager-level equivalent of a compare-and-swap. The
    Python GIL makes the read+write effectively atomic for a single
    attribute on a single object, so no lock is needed.

    Used by cancel_job to avoid racing with the worker pulling the
    job off the queue.
    """
    if job.status != expected:
        return False
    job.status = new
    return True


class PriorityRequestManager:
    """
    Manages generation requests with priority queuing and resource cleanup.
    Ensures single-threaded execution of model inference to prevent VRAM OOM.
    """

    def __init__(
        self,
        device="cuda",
        max_concurrent=1,
        max_history: int = 1000,
        max_queue_size: int = 4,
        store: JobStore | None = None,
        max_age_seconds: int = 86_400,
        model_path: str = "tencent/Hunyuan3D-2mini",
        model_subfolder: str = "hunyuan3d-dit-v2-mini-turbo",
        multiview_model: str = "tencent/Hunyuan3D-2mv",
        multiview_subfolder: str = "hunyuan3d-dit-v2-mv",
        t2i_model: str | None = None,
        inference_service: "InferenceService | None" = None,
    ):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.jobs: dict[str, JobResponse] = {}
        # Set once the initial rehydrate pass has finished. ``/health``
        # is a liveness probe and does not wait on it; ``/ready`` does.
        self._ready_event = asyncio.Event()
        self._rehydrate_task: asyncio.Task | None = None
        self.device = device
        self.model_path = model_path
        self.model_subfolder = model_subfolder
        self.multiview_model = multiview_model
        self.multiview_subfolder = multiview_subfolder
        self.t2i_model = t2i_model
        self.max_age_seconds = max_age_seconds
        self._shutdown_event = asyncio.Event()
        self._worker_task: asyncio.Task | None = None
        self._retention_task: asyncio.Task | None = None

        # Cap the in-memory job history so a long-running server doesn't grow
        # unbounded. Old completed/failed/cancelled jobs are evicted when the
        # dictionary exceeds ``max_history`` entries. 0 disables the cap.
        self.max_history = max_history
        self.max_queue_size = max_queue_size
        self._evicted_total = 0

        # Most recent worker error (string) so /health can surface it.
        # Cleared automatically on the next successful job.
        self.last_error: str | None = None

        # Optional SQLite-backed persistence. When set, every job transition
        # is mirrored to disk and the in-memory state is rehydrated on start.
        self.store: JobStore | None = store

        # Per-job subscribers. ``subscribers[uid]`` is a list of asyncio
        # Queues; on each status change we put the new JobResponse on every
        # queue. SSE handlers consume one queue each.
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._subs_lock = threading.Lock()
        # List-level subscribers (one queue per consumer). On every job
        # change we broadcast the current full list to all of these.
        # Used by the gallery page to update without polling.
        self._list_subscribers: list[asyncio.Queue] = []
        self._list_subs_lock = threading.Lock()

        # Lazy initialization of the worker to speed up startup.
        # ``worker`` is now an alias for the InferenceService's underlying
        # ``ModelWorker`` so legacy code that introspects it keeps working.
        self.worker: ModelWorker | None = None

        # Optional shared inference service. When provided, ``start()``
        # delegates queue + worker management to the service and the
        # manager's own loop becomes a thin adapter that mirrors events
        # onto SSE. When None, the manager falls back to its embedded
        # loop (preserves the original behaviour for tests).
        from hy3dgen.api.inference_service import InferenceService

        self.inference_service: InferenceService | None = inference_service
        self._service_listener: asyncio.Queue | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def rehydrate(self) -> int:
        """Restore jobs from the persistent store into memory.

        Returns the number of jobs rehydrated. Active jobs (queued or
        processing) that have a stored payload are reconstructed and
        re-queued so they actually resume after a restart. Active jobs
        that lack a payload (legacy DB, or written by an older version)
        are marked FAILED with a clear error. Terminal jobs are loaded
        as-is to preserve the history.
        """
        if self.store is None:
            return 0
        # Lazy import to avoid a hard dependency at module load.
        from hy3dgen.api.config import SAVE_DIR

        count = 0
        replayed = 0
        async for job, payload in self.store.restore_all():
            self.jobs[job.uid] = job
            count += 1
            if job.status not in (JobStatus.QUEUED, JobStatus.PROCESSING):
                continue
            if not payload:
                # Legacy job whose payload wasn't persisted. Mark it
                # failed so the user can see the reason and resubmit.
                job.status = JobStatus.FAILED
                job.error = (
                    "Server restarted while this job was in-flight and "
                    "its original request payload was not stored. "
                    "Please resubmit."
                )
                job.completed_at = utc_now()
                await self._persist(job)
                self._notify(job)
                logger.warning(f"Cannot replay job {job.uid}: payload missing.")
                continue
            try:
                request = _request_from_payload(payload)
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = f"Stored payload could not be deserialized: {e}"
                job.completed_at = utc_now()
                await self._persist(job)
                self._notify(job)
                logger.warning(f"Cannot replay job {job.uid}: bad payload ({e}).")
                continue
            # Mid-flight jobs use a low priority (high number) so we
            # don't jump in front of anything new.
            job.status = JobStatus.QUEUED
            job.updated_at = utc_now()
            job.request_type = request.type
            await self._persist(job)
            if self.inference_service is not None:
                params = request.model_dump(mode="json", exclude_none=True)
                params["uid"] = job.uid
                await self.inference_service.submit_recovered(params, save_dir=SAVE_DIR)
            else:
                await self.queue.put((100, time.time(), job.uid, request, SAVE_DIR))
            replayed += 1
            logger.info(f"Re-queued active job {job.uid} after restart.")
        logger.info(
            f"Rehydrated {count} jobs from persistent store ({replayed} re-queued for replay)."
        )
        return count

    async def start(self, *, await_rehydrate: bool = True):
        """Start the background worker loop.

        When an ``InferenceService`` was injected at construction
        time, we delegate queue + worker management to it and only
        attach an event listener that mirrors service events onto
        SSE. Otherwise we fall back to the embedded loop (the
        original behaviour preserved for unit tests that mock the
        worker directly).

        When a store is attached, rehydration runs as a background task so a
        large job history does not block readiness; pass
        ``await_rehydrate=True`` to block instead (used by tests and
        callers that need the store fully loaded when ``start()``
        returns).
        """
        if self._worker_task is None:
            if self.inference_service is not None:
                await self.inference_service.start()
                self._service_listener = self.inference_service.subscribe()
                self._worker_task = asyncio.create_task(
                    self._mirror_service_events(), name="api-mirror-service"
                )
                logger.info("PriorityRequestManager delegating to InferenceService.")
            else:
                self._worker_task = asyncio.create_task(self._process_queue())
                logger.info("PriorityRequestManager worker started.")
            if self.store is not None:
                if await_rehydrate:
                    await self.rehydrate()
                    self._ready_event.set()
                else:
                    self._rehydrate_task = asyncio.create_task(
                        self._rehydrate_then_signal(), name="api-rehydrate"
                    )
            else:
                self._ready_event.set()
            if self._retention_task is None:
                self._retention_task = asyncio.create_task(
                    self._retention_loop(), name="api-retention"
                )

    async def _rehydrate_then_signal(self) -> None:
        """Run ``rehydrate()`` and always release readiness afterwards.

        A failure here must not leave the server permanently unready,
        so the flag is set even when rehydration raises.
        """
        try:
            await self.rehydrate()
        except Exception:
            logger.exception("Rehydrate failed; continuing with in-memory-only state.")
        finally:
            self._ready_event.set()

    @property
    def ready(self) -> bool:
        """True when there is nothing left to wait for.

        With no persistent store there is nothing to rehydrate, so the
        manager is ready as soon as it exists. Otherwise readiness flips
        once the initial rehydrate pass finishes.
        """
        if self.store is None:
            return True
        return self._ready_event.is_set()

    @property
    def queue_depth(self) -> int:
        """Number of pending jobs in the active queue implementation."""
        if self.inference_service is not None:
            return self.inference_service.queue_size
        return self.queue.qsize()

    @property
    def model_loaded(self) -> bool:
        """Whether the active worker has loaded its shape pipeline."""
        if self.inference_service is not None:
            return self.inference_service.model_loaded
        return self.worker is not None and getattr(self.worker, "pipeline", None) is not None

    async def wait_ready(self, timeout: float | None = None) -> bool:
        """Await readiness. Returns True if ready, False on timeout."""
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def stop(self):
        """Stop the worker loop gracefully."""
        self._shutdown_event.set()
        if self._retention_task is not None:
            self._retention_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retention_task
            self._retention_task = None
        if self._rehydrate_task is not None:
            self._rehydrate_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._rehydrate_task
            self._rehydrate_task = None
        self._ready_event.set()
        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
        if self._service_listener is not None and self.inference_service is not None:
            self.inference_service.unsubscribe(self._service_listener)
            self._service_listener = None
            await self.inference_service.stop()
        await self._drain_queue_on_shutdown()
        logger.info("PriorityRequestManager worker stopped.")

    async def _mirror_service_events(self) -> None:
        """Forward service-level events to JobResponse updates + SSE."""
        from hy3dgen.api.inference_service import JobStage as ServiceStage

        if self._service_listener is None:
            return
        while not self._shutdown_event.is_set():
            try:
                event = await asyncio.wait_for(self._service_listener.get(), timeout=0.5)
                self._service_listener.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            self._apply_service_event(event)
            if event.stage in (ServiceStage.COMPLETED, ServiceStage.FAILED, ServiceStage.CANCELLED):
                await self._aggressive_cleanup()
            # Touch the namespace to satisfy linters in case it's not used.
            _ = ServiceStage

    def _apply_service_event(self, event: "InferenceEvent") -> None:
        """Translate an ``InferenceEvent`` into JobResponse mutations + SSE."""
        from hy3dgen.api.inference_service import JobStage as ServiceStage

        job = self.jobs.get(event.uid)
        if job is None:
            # Best-effort: create a stub so SSE clients see the event.
            job = JobResponse(
                uid=event.uid,
                status=JobStatus.QUEUED,
                request_type=event.request_type,
                created_at=utc_now(),
            )
            self.jobs[event.uid] = job
        stage = event.stage
        if stage == ServiceStage.QUEUED:
            job.status = JobStatus.QUEUED
            job.request_type = event.request_type
        elif stage == ServiceStage.LOADING_MODEL:
            job.status = JobStatus.PROCESSING
            job.stage = "loading_model"
        elif stage == ServiceStage.SHAPE_GENERATION:
            job.status = JobStatus.PROCESSING
            job.stage = "shape_generation"
        elif stage == ServiceStage.TEXTURE:
            job.status = JobStatus.PROCESSING
            job.stage = "texture"
        elif stage == ServiceStage.EXPORTING:
            job.status = JobStatus.PROCESSING
            job.stage = "exporting"
        elif stage == ServiceStage.COMPLETED:
            job.status = JobStatus.COMPLETED
            job.file_path = event.file_path
            job.completed_at = utc_now()
        elif stage == ServiceStage.FAILED:
            job.status = JobStatus.FAILED
            job.error = event.error
            job.completed_at = utc_now()
        elif stage == ServiceStage.CANCELLED:
            job.status = JobStatus.CANCELLED
            job.error = event.error or "Cancelled by user"
            job.completed_at = utc_now()
        if event.progress is not None:
            job.stage_progress = max(0.0, min(1.0, float(event.progress)))
        if event.error is not None:
            self.last_error = event.error
        elif stage == ServiceStage.COMPLETED:
            self.last_error = None
        job.updated_at = utc_now()
        # Persist + notify SSE subscribers.
        task = asyncio.create_task(self._persist(job))
        self._track_persist_task(task)
        self._notify(job)

    def _track_persist_task(self, task: asyncio.Task) -> None:
        """Hold a strong reference to a background persist task.

        Without this, the GC can collect the task before the
        ``_persist`` coroutine completes, which logs a warning and
        risks losing the update.
        """
        bag = getattr(self, "_persist_tasks", None)
        if bag is None:
            bag = set()
            self._persist_tasks = bag
        bag.add(task)
        task.add_done_callback(bag.discard)

    async def submit_job(
        self,
        request: JobRequest,
        save_dir: str,
        priority: int = 10,
        _payload: dict | None = None,
    ) -> str:
        """Submit a job to the queue.

        When an ``InferenceService`` is configured, submission is
        delegated and the service's worker handles execution. The
        manager still creates the ``JobResponse`` and persists /
        notifies so HTTP clients see the same behaviour.

        Args:
            request: The generation request (polymorphic)
            save_dir: Directory to save output
            priority: Lower number = higher priority. Default 10.
            _payload: Optional serialised request (used by rehydration
                so the original request body can be replayed after a
                restart). Normally callers should pass only ``request``
                and let ``_payload`` default to ``request.model_dump()``.

        Returns:
            uid: The unique job ID
        """
        uid = str(uuid.uuid4())
        job = JobResponse(
            uid=uid,
            status=JobStatus.QUEUED,
            created_at=utc_now(),
            request_type=request.type if request else None,
        )
        self.jobs[uid] = job

        if self.inference_service is not None:
            params = (request.model_dump() if request else {}) or {}
            params.setdefault("uid", uid)
            try:
                await self.inference_service.submit(params, save_dir=save_dir)
            except asyncio.QueueFull:
                self.jobs.pop(uid, None)
                raise
            logger.info(f"Job {uid} delegated to InferenceService")
            await self._persist(job, payload=_payload or params)
            self._notify(job)
            return uid

        # Queue item: (priority, timestamp, uid, request, save_dir)
        # timestamp acts as secondary sort key for FIFO within same priority
        try:
            self.queue.put_nowait((priority, time.time(), uid, request, save_dir))
        except asyncio.QueueFull:
            self.jobs.pop(uid, None)
            raise
        logger.info(f"Job {uid} queued with priority {priority}")
        # Persist the initial state and notify any early subscribers.
        await self._persist(job, payload=_payload or (request.model_dump() if request else None))
        self._notify(job)
        return uid

    async def submit_unified(
        self,
        request: GenerationRequest,
        save_dir: str,
        priority: int = 10,
    ) -> str:
        """Submit a job from the unified ``GenerationRequest`` schema.

        The request is converted to the internal ``JobRequest`` variant
        for dispatch, but the unified form is what we persist (so a
        restart can reconstruct the exact API surface the user sent).
        """
        internal = request.to_internal_request()
        unified_payload = request.model_dump(mode="json", exclude_none=True)
        uid = await self.submit_job(
            request=internal,
            save_dir=save_dir,
            priority=priority,
            _payload=unified_payload,
        )
        JOBS_SUBMITTED.labels(mode=internal.type).inc()
        JOBS_IN_MEMORY.set(len(self.jobs))
        return uid

    def get_job(self, uid: str) -> JobResponse | None:
        return self.jobs.get(uid)

    def warmup_model(self) -> str:
        """Eagerly load the inference model.

        Returns one of:
          - ``"already_loaded"`` when ``ModelWorker.pipeline`` is set.
          - ``"loading"`` when a new load was scheduled.
          - ``"queued"`` when no service is configured (the embedded
            path will lazy-load on the next job submission).

        The actual download + weight load runs in a worker thread;
        this method only schedules it. Callers can poll
        ``/v1/models/status`` or just submit a job once the model is
        ready.
        """
        worker = self.worker
        if worker is not None and getattr(worker, "pipeline", None) is not None:
            return "already_loaded"

        async def _trigger() -> None:
            """Build a ModelWorker so weights are downloaded + loaded.

            We do this in a thread via ``asyncio.to_thread`` so the
            event loop stays responsive during the (potentially
            long) HF download. Errors are recorded on
            ``manager.last_error`` so the UI can surface them via
            ``/v1/models/status``.
            """
            from hy3dgen.inference import ModelWorker

            try:
                self.worker = await asyncio.to_thread(
                    ModelWorker,
                    device=self.device,
                    model_path=self.model_path,
                    subfolder=self.model_subfolder,
                    multiview_model_path=self.multiview_model,
                    multiview_subfolder=self.multiview_subfolder,
                    t2i_model_path=self.t2i_model,
                    enable_tex=True,
                    enable_t2i=True,
                )
            except Exception as exc:
                self.last_error = f"warmup failed: {exc}"
                logger.exception("warmup_model failed")

        # Schedule without blocking. The caller gets an immediate
        # ``"loading"`` status; the actual download happens on the
        # event loop. If we don't have a running loop (e.g. called
        # from a sync test), fall back to a thread.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop — most likely a test fixture. The caller can
            # poll the manager.worker attribute later.
            import threading

            def _runner() -> None:
                try:
                    self.worker = ModelWorker(
                        device=self.device,
                        model_path=self.model_path,
                        subfolder=self.model_subfolder,
                        multiview_model_path=self.multiview_model,
                        multiview_subfolder=self.multiview_subfolder,
                        t2i_model_path=self.t2i_model,
                        enable_tex=True,
                        enable_t2i=True,
                    )
                except Exception as exc:
                    self.last_error = f"warmup failed: {exc}"

            threading.Thread(target=_runner, daemon=True).start()
            return "queued"

        task = loop.create_task(_trigger())
        # Keep a strong reference so the task isn't garbage-collected
        # mid-flight; the manager already has a _persist_tasks bag
        # for the same pattern.
        self._track_persist_task(task)
        return "loading"

    def set_stage(self, uid: str, stage: str, progress: float | None = None) -> None:
        """Update the stage label and progress for a running job.

        Called by the inference worker during execution to surface
        fine-grained state ("loading_model", "shape_generation",
        "texturing", "exporting") to the UI. The change is persisted
        and broadcast to subscribers, just like any other transition.
        ``progress`` is a float in [0, 1]; pass ``None`` when unknown.
        """
        job = self.jobs.get(uid)
        if job is None:
            return
        job.stage = stage
        if progress is not None:
            try:
                job.stage_progress = max(0.0, min(1.0, float(progress)))
            except (TypeError, ValueError):
                job.stage_progress = None
        # Persist + notify asynchronously to keep this hot-path non-blocking.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._persist(job))
        # Hold the task reference so the GC doesn't drop it mid-flight.
        self._track_persist_task(task)
        self._notify(job)

    @staticmethod
    def _body_byte_limit() -> int | None:
        # Imported here so the manager stays importable when tests stub
        # ``hy3dgen.api.config`` for isolation. The module object (not a
        # bound ``settings`` value) is used so config reloads stay visible.
        from hy3dgen.api import config as config_module

        return config_module.settings.max_body_bytes or None

    def capabilities(self) -> dict:
        """Return a snapshot of static + dynamic state for ``/v1/capabilities``.

        When an ``InferenceService`` is configured, the snapshot is
        delegated to the service (which can include calibrated preset
        timings). Otherwise the legacy worker-introspection path runs.
        Either way the response shape matches ``CapabilitiesResponse``.
        """
        # Imported here so the manager stays importable when tests stub
        # ``hy3dgen.inference`` for isolation.
        from hy3dgen.inference import (
            MAX_IMAGE_BYTES,
            MAX_MESH_BYTES,
            model_capability_snapshot,
            worker_model_state,
        )

        if self.inference_service is not None:
            snap = self.inference_service.capabilities()
        else:
            worker = self.worker
            snap = model_capability_snapshot(
                worker_model_state(
                    worker,
                    {
                        "shape_model": self.model_path,
                        "shape_subfolder": self.model_subfolder,
                        "multiview_model": self.multiview_model,
                        "multiview_subfolder": self.multiview_subfolder,
                        "t2i_model": self.t2i_model,
                    },
                )
            )
            snap["presets"] = {
                "fast": {"steps": 5, "guidance": 5.0, "octree_resolution": 192},
                "balanced": {"steps": 50, "guidance": 5.0, "octree_resolution": 256},
                "detailed": {"steps": 100, "guidance": 7.5, "octree_resolution": 384},
            }
        snap["limits"] = {
            "image_bytes": MAX_IMAGE_BYTES,
            "mesh_bytes": MAX_MESH_BYTES,
            "queue_depth": self.max_queue_size,
            "body_bytes": self._body_byte_limit(),
        }
        snap["version"] = __version__
        return snap

    async def evict_old_jobs(self, max_age_seconds: int = 24 * 3600) -> int:
        """Drop completed/failed/cancelled jobs older than ``max_age_seconds``.

        Active (queued/processing) jobs are never evicted. Returns the number
        of jobs removed. Call this from a periodic task or after each
        completed job to keep memory bounded.
        """
        cutoff = time.time() - max_age_seconds
        terminal_statuses = (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        victims: list[tuple[float, str]] = []  # (created_ts, uid)
        for uid, job in self.jobs.items():
            if job.status not in terminal_statuses or not job.created_at:
                continue
            try:
                created_ts = timestamp(job.created_at)
            except ValueError:
                continue
            if created_ts < cutoff:
                victims.append((created_ts, uid))
        # Oldest first; sort ensures determinism when many jobs share a timestamp.
        victims.sort()
        for _, uid in victims:
            del self.jobs[uid]
            self._evicted_total += 1
            if self.store is not None:
                await self.store.delete(uid)
        if victims:
            logger.info(f"Evicted {len(victims)} old jobs (older than {max_age_seconds}s).")
            self._notify_list()
        return len(victims)

    async def evict_to_size(self) -> int:
        """If ``max_history`` is set and exceeded, drop the oldest terminal jobs.

        Returns the number evicted.
        """
        if self.max_history <= 0 or len(self.jobs) <= self.max_history:
            return 0
        terminal_statuses = (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        sortable: list[tuple[str, float]] = []
        for uid, job in self.jobs.items():
            if job.status in terminal_statuses and job.created_at:
                try:
                    created_ts = timestamp(job.created_at)
                except ValueError:
                    created_ts = 0.0
                sortable.append((uid, created_ts))
        sortable.sort(key=lambda pair: pair[1])  # oldest first
        to_remove = len(self.jobs) - self.max_history
        for uid, _ in sortable[:to_remove]:
            await self._delete_job_artifact(self.jobs[uid])
            del self.jobs[uid]
            self._evicted_total += 1
            if self.store is not None:
                await self.store.delete(uid)
        if to_remove > 0:
            logger.info(f"Evicted {to_remove} jobs to respect max_history={self.max_history}.")
            self._notify_list()
        return to_remove

    async def cleanup_files_older_than(
        self, max_age_seconds: int, save_dir: str | None = None
    ) -> int:
        """Delete mesh files older than ``max_age_seconds`` from disk.

        This is the **disk** half of retention: it never touches the DB.
        Use ``store.delete_older_than`` for the DB half. The two are
        intentionally separate so a SQLite reset doesn't accidentally destroy
        artifacts the user might still want to download.
        """
        import pathlib

        if max_age_seconds <= 0:
            return 0
        if save_dir is None:
            from hy3dgen.api.config import SAVE_DIR

            base = pathlib.Path(SAVE_DIR)
        else:
            base = pathlib.Path(save_dir)
        if self.store is not None:
            victims: list[JobResponse] = await self.store.list_older_than(max_age_seconds)
        else:
            cutoff = time.time() - max_age_seconds
            terminal_statuses = {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }
            victims = []
            for job in self.jobs.values():
                if job.status not in terminal_statuses or not job.created_at:
                    continue
                try:
                    expired = timestamp(job.created_at) < cutoff
                except ValueError:
                    continue
                if expired:
                    victims.append(job)
        removed = 0
        for job in victims:
            if await self._delete_job_artifact(job, save_dir=str(base)):
                removed += 1
        if removed:
            logger.info(f"Removed {removed} mesh file(s) older than {max_age_seconds}s.")
        return removed

    async def _delete_job_artifact(
        self, job: JobResponse, *, save_dir: str | None = None
    ) -> bool:
        """Delete a job artifact only when its resolved path stays in SAVE_DIR."""
        import pathlib

        if not job.file_path:
            return False
        if save_dir is None:
            from hy3dgen.api.config import SAVE_DIR

            base = pathlib.Path(SAVE_DIR).resolve()
        else:
            base = pathlib.Path(save_dir).resolve()
        path = pathlib.Path(job.file_path)
        if not path.is_absolute():
            path = base / path.name
        path = path.resolve()
        try:
            path.relative_to(base)
        except ValueError:
            logger.warning("Refusing to remove artifact outside SAVE_DIR: %s", path)
            return False
        try:
            if path.is_file():
                path.unlink()
                return True
        except OSError as exc:
            logger.warning("Failed to remove artifact %s: %s", path, exc)
        return False

    async def cancel_job(self, uid: str) -> bool:
        # We can only cancel jobs that are still in the queue.
        # Anything already processing is mid-inference and can't be
        # safely interrupted from here (ModelWorker is a blocking call
        # running in a thread). We log a warning so the caller knows
        # their cancel request was a no-op rather than silently failing.
        job = self.jobs.get(uid)
        if job is None:
            return True
        if job.status == JobStatus.PROCESSING:
            logger.warning(
                f"cancel_job({uid}): job is already processing; cannot interrupt "
                f"in-flight inference. Wait for completion or failure."
            )
            return False
        if job.status != JobStatus.QUEUED:
            return True
        if self.inference_service is not None:
            if not await self.inference_service.cancel(uid):
                return False
        # Atomic check-and-set: only flip the status if it's still QUEUED.
        # Without this guard, a racing _process_queue could have already
        # moved the job to PROCESSING between our get() and the status
        # write, leaving us with a CANCELLED job that still ran.
        if not _status_transition(job, JobStatus.QUEUED, JobStatus.CANCELLED):
            logger.debug(f"cancel_job({uid}): status changed under us, skipping")
            return False
        job.error = "Cancelled by user"
        job.completed_at = utc_now()
        job.updated_at = job.completed_at
        logger.info(f"Job {uid} cancelled")
        await self._persist(job)
        self._notify(job)
        return True

    async def _process_queue(self):
        while not self._shutdown_event.is_set():
            try:
                _, _, uid, request, save_dir = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=0.5,
                )
                try:
                    # Check status; cancel/fail means we skip the job but
                    # still mark the queue slot done so task_done() counts
                    # stay balanced.
                    if uid not in self.jobs or self.jobs[uid].status in (
                        JobStatus.CANCELLED,
                        JobStatus.FAILED,
                    ):
                        continue

                    # Re-check shutdown before starting an expensive
                    # inference - we don't want to spin up a new job
                    # while the user is trying to stop the server.
                    if self._shutdown_event.is_set():
                        await self.cancel_job(uid)
                        break

                    # Run job
                    await self._execute_model_worker(uid, request, save_dir)
                finally:
                    # Always mark the queue slot done, even on exception
                    # (the previous version only called task_done on the
                    # happy path, which could leak unfinished-task
                    # counters and break queue.join() callers).
                    self.queue.task_done()

                # Cleanup
                await self._aggressive_cleanup()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(1)  # Backoff

    async def _execute_model_worker(self, uid: str, request: JobRequest, save_dir: str):
        job = self.jobs[uid]
        job.status = JobStatus.PROCESSING
        await self._persist(job)
        self._notify(job)
        span = start_span(
            "polyforge.job.execute",
            **{"job.uid": uid, "job.mode": getattr(request, "type", "unknown")},
        )

        try:
            # Validate texture_mesh has a reference (image or prompt) before
            # spinning up the worker.
            if (
                request
                and request.type == "texture_mesh"
                and not getattr(request, "has_reference", False)
            ):
                raise ValueError("texture_mesh requires at least one of: image, prompt.")

            # If we were rehydrated after a restart, request is None; we
            # can't replay the job without its original payload. Mark it
            # failed and move on.
            if request is None:
                raise RuntimeError(
                    "Job payload missing (server restarted mid-flight). Cannot replay."
                )

            # Initialize worker if needed (Lazy Loading)
            if self.worker is None:
                logger.info("Initializing ModelWorker (Lazy Load)...")
                self.set_stage(uid, "loading_model", 0.05)
                # Blocking init logic, run in thread to avoid freezing API?
                # Model loading is heavy.
                self.worker = await asyncio.to_thread(
                    ModelWorker,
                    device=self.device,
                    model_path=self.model_path,
                    subfolder=self.model_subfolder,
                    multiview_model_path=self.multiview_model,
                    multiview_subfolder=self.multiview_subfolder,
                    t2i_model_path=self.t2i_model,
                    enable_tex=True,
                    enable_t2i=True,
                )
                self.set_stage(uid, "loading_model", 0.3)

            # Prepare params dict from Pydantic model
            params = request.model_dump()

            # Map Pydantic fields to ModelWorker expectations
            if request.type == "text_to_3d":
                params["text"] = request.prompt
            elif request.type == "texture_mesh":
                # texture_mesh implies texture=True; ModelWorker also expects the
                # mesh (base64) to be present in params under the 'mesh' key, and
                # a guidance image/prompt under 'image'/'text'.
                params["texture"] = True
                if request.prompt and "text" not in params:
                    params["text"] = request.prompt

            # Mark generation stage before the heavy lifting.
            self.set_stage(uid, "shape_generation", 0.4)

            # Run generation in thread
            logger.info(f"Starting generation for job {uid}")
            file_path = await asyncio.to_thread(self.worker.generate, uid, params, save_dir)

            # If the user requested texture and the worker produced one,
            # the texture stage happened inside ``worker.generate`` already;
            # we just round the progress up to "finished" here.
            self.set_stage(uid, "exporting", 0.95)

            job.status = JobStatus.COMPLETED
            job.file_path = file_path
            job.completed_at = utc_now()
            logger.info(f"Job {uid} completed successfully")
            # Clear the last_error latch after a success.
            self.last_error = None
            JOBS_COMPLETED.inc()
            if job.created_at:
                try:
                    start_ts = timestamp(job.created_at)
                    JOB_DURATION.observe(time.time() - start_ts)
                except ValueError:
                    pass
            end_span(span)
            await self._persist(job)
            self._notify(job)

        except Exception as e:
            logger.error(f"Job {uid} failed: {e}")
            import traceback

            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utc_now()
            # Track the most recent failure so /health can surface it.
            self.last_error = f"{type(e).__name__}: {e}"
            JOBS_FAILED.labels(reason=type(e).__name__).inc()
            end_span(span, error=e)
            await self._persist(job)
            self._notify(job)

    async def _drain_queue_on_shutdown(self) -> None:
        """Called when the worker is stopping. Marks any pending QUEUED
        jobs as CANCELLED so the user sees a clear reason rather than
        the jobs silently disappearing.
        """
        drained = 0
        while not self.queue.empty():
            try:
                _, _, uid, _request, _save_dir = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            job = self.jobs.get(uid)
            if job is not None and job.status == JobStatus.QUEUED:
                _status_transition(job, JobStatus.QUEUED, JobStatus.CANCELLED)
                job.error = "Server shutting down"
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                await self._persist(job)
                self._notify(job)
                drained += 1
            self.queue.task_done()
        if drained:
            logger.info(f"Drained {drained} queued job(s) on shutdown")

    async def _retention_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self.wait_ready()
                await self._aggressive_cleanup()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Periodic retention cleanup failed.")
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                continue

    async def _aggressive_cleanup(self):
        """Perform aggressive garbage collection and bounded history cleanup."""
        gc.collect()
        import sys

        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        # Keep the in-memory history bounded. We don't evict on every job
        # (would be wasteful for short bursts), but we do check periodically.
        if self.max_history > 0 and len(self.jobs) > self.max_history:
            await self.evict_to_size()
        if self.max_age_seconds > 0:
            await self.cleanup_files_older_than(self.max_age_seconds)
            await self.evict_old_jobs(self.max_age_seconds)

    # ------------------------------------------------------------------
    # Persistence + pub/sub
    # ------------------------------------------------------------------

    async def _persist(self, job: JobResponse, payload: dict | None = None) -> None:
        """Mirror a job transition to the persistent store. No-op without one."""
        job.updated_at = utc_now()
        if self.store is None:
            return
        try:
            await self.store.upsert(job, request_payload=payload)
        except Exception as e:  # never let persistence failures kill the worker
            logger.warning(f"Failed to persist job {job.uid}: {e}")

    def _notify(self, job: JobResponse) -> None:
        """Fan out a job update to every subscriber of this uid, and to
        list-level subscribers (one event per change, payload is the
        current full list)."""
        with self._subs_lock:
            queues = list(self._subscribers.get(job.uid, ()))
        for q in queues:
            while q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                    q.task_done()
            try:
                q.put_nowait(job.model_copy(deep=True))
            except asyncio.QueueFull:  # pragma: no cover - access is event-loop local
                logger.warning(f"Subscriber queue full for {job.uid}; dropping event")
        # Then notify list subscribers with a fresh snapshot.
        if self._list_subscribers:
            self._notify_list()

    def _notify_list(self) -> None:
        """Send the current job list to every list-level subscriber.

        We send the full list (not a diff) so the consumer can simply
        replace its state. List size is bounded by max_history and the
        SSE payload is small (one JSON per uid).
        """
        with self._list_subs_lock:
            listeners = list(self._list_subscribers)
        if not listeners:
            return
        snapshot = sorted(
            (job.model_copy(deep=True) for job in self.jobs.values()),
            key=lambda j: j.created_at or "",
            reverse=True,
        )
        for q in listeners:
            while q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                    q.task_done()
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:  # pragma: no cover - access is event-loop local
                logger.warning("List subscriber queue full; dropping event")

    async def subscribe(self, uid: str) -> asyncio.Queue:
        """Register a new subscriber for ``uid`` and return its queue.

        The caller is expected to read the queue and call
        ``unsubscribe(uid, queue)`` when done. The first item on the
        queue is the current job state (so consumers don't have to
        separately fetch it).
        """
        # Bounded buffer so a slow consumer can't be OOM'd. 64 transitions
        # is far more than any real job will ever emit; if the consumer
        # falls further behind, ``_notify`` will start dropping the oldest
        # entry to make room.
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._subs_lock:
            self._subscribers.setdefault(uid, []).append(q)
        # Prime the queue with the current state so the consumer has it
        # immediately, even if no further transitions happen.
        current = self.jobs.get(uid)
        if current is None and self.store is not None:
            current = await self.store.get(uid)
        if current is not None:
            q.put_nowait(current.model_copy(deep=True))
        return q

    def unsubscribe(self, uid: str, queue: asyncio.Queue) -> None:
        with self._subs_lock:
            listeners = self._subscribers.get(uid)
            if not listeners:
                return
            with contextlib.suppress(ValueError):
                listeners.remove(queue)
            if not listeners:
                self._subscribers.pop(uid, None)

    def subscribe_list(self) -> asyncio.Queue:
        """Register a new list-level subscriber.

        The first item on the queue is the current snapshot of the
        in-memory job list, so consumers don't need a separate fetch.
        Subsequent items are also full snapshots, sorted by created_at
        desc.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        with self._list_subs_lock:
            self._list_subscribers.append(q)
        # Prime with the current snapshot.
        q.put_nowait(
            sorted(
                (job.model_copy(deep=True) for job in self.jobs.values()),
                key=lambda j: j.created_at or "",
                reverse=True,
            )
        )
        return q

    def unsubscribe_list(self, queue: asyncio.Queue) -> None:
        with self._list_subs_lock, contextlib.suppress(ValueError):
            self._list_subscribers.remove(queue)


# ---------------------------------------------------------------------------
# Rehydration helpers
# ---------------------------------------------------------------------------

# Map the ``type`` discriminator to the concrete Pydantic model class.
# We can't use ``TypeAdapter(JobRequest)`` here because the union is
# declared with ``Annotated[..., Field(discriminator='type')]`` and
# Pydantic 2.13 has a bug with that combo. Instead we look up the class
# by name from the JSON tag.
_REQUEST_CLASSES: dict = {
    "text_to_3d": None,  # filled in lazily to avoid an import cycle
    "image_to_3d": None,
    "multiview": None,
    "texture_mesh": None,
}


def _request_from_payload(payload: dict):
    """Reconstruct a JobRequest (or one of its union members) from a dict.

    Used by ``PriorityRequestManager.rehydrate`` to rebuild the original
    request from a payload we stored in SQLite.

    Two shapes are supported:
    - **Unified** (post #7): no ``type`` field, has ``text``/``image``/
      ``views``/``mesh``. Converted via ``GenerationRequest.to_internal_request()``.
    - **Legacy** (pre #7): has a ``type`` field. Dispatched by tag.
    """
    from hy3dgen.api.schemas import (
        GenerationRequest,
        ImageTo3DRequest,
        MultiviewRequest,
        TextTo3DRequest,
        TextureMeshRequest,
    )

    if _REQUEST_CLASSES["text_to_3d"] is None:
        _REQUEST_CLASSES.update(
            {
                "text_to_3d": TextTo3DRequest,
                "image_to_3d": ImageTo3DRequest,
                "multiview": MultiviewRequest,
                "texture_mesh": TextureMeshRequest,
            }
        )
    if not isinstance(payload, dict):
        raise ValueError(f"Payload is not a dict: {type(payload).__name__}")

    # Unified form: no ``type`` tag, just inputs + common params.
    if "type" not in payload:
        unified = GenerationRequest.model_validate(payload)
        return unified.to_internal_request()

    # Legacy form: dispatch by ``type``.
    tag = payload.get("type")
    if tag not in _REQUEST_CLASSES:
        raise ValueError(f"Unknown request type: {tag!r}")
    cls = _REQUEST_CLASSES[tag]
    if cls is None:
        raise ValueError(f"Request class for type {tag!r} not registered")
    return cls.model_validate(payload)
