import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from hy3dgen.api import signed_urls
from hy3dgen.api.config import SAVE_DIR
from hy3dgen.api.deps import get_manager, get_mesh_processor
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.schemas import (
    CapabilitiesResponse,
    GenerationRequest,
    JobRequest,
    JobResponse,
    JobStatus,
    LibraryResponse,
    MeshOpsRequest,
)
from hy3dgen.meshops.processor import MeshProcessor
from hy3dgen.monitoring import get_system_metrics
from hy3dgen.version import __version__

router = APIRouter(prefix="/v1", tags=["generation"])

# Terminal job states that should close the SSE stream.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Type aliases for the modern Annotated-dependency style.
# (FastAPI >= 0.95 prefers `x: Annotated[T, Depends(...)]` over
# `x: T = Depends(...)` for type-checker compatibility.)
ManagerDep = Annotated[PriorityRequestManager, Depends(get_manager)]
MeshProcessorDep = Annotated[MeshProcessor, Depends(get_mesh_processor)]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SignedFileResponse(BaseModel):
    """Response schema for the signed-URL endpoint."""

    url: str
    expires_at: int
    ttl_seconds: int


class ModelLoadResponse(BaseModel):
    """Response schema for ``POST /v1/models/load``.

    The endpoint is async — the actual download / weight load runs in
    a thread on the inference worker. Clients poll
    ``GET /v1/models/status`` to see when the model is ready.
    """

    status: str
    model: str
    started_at: str


class ModelStatusResponse(BaseModel):
    """Response schema for ``GET /v1/models/status``."""

    loaded: bool
    loading: bool
    model: str
    subfolder: str | None = None
    device: str
    last_error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# Submission endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=202,
    summary="Submit a generation job (legacy polymorphic)",
    description=(
        "Accepts the discriminated-union body "
        '`{ "type": "text_to_3d" | "image_to_3d" | "multiview" | "texture_mesh", ... }`. '
        "New code should use `POST /v1/generate` instead — the unified schema "
        "infers the mode from the fields you fill in."
    ),
)
async def submit_job(
    request: JobRequest,
    manager: ManagerDep,
) -> JobResponse:
    """Submit a generation job. Returns 202 with the initial status."""
    uid = await manager.submit_job(request, SAVE_DIR)
    return manager.get_job(uid)  # type: ignore[return-value]


@router.post(
    "/generate",
    response_model=JobResponse,
    status_code=202,
    summary="Submit a unified generation job",
    description=(
        "All input fields are optional at the type level; the backend infers "
        "the generation mode from what's filled in. See `GenerationRequest` "
        "for the dispatch rules. Common params (`seed`, `steps`, `guidance`, "
        "`octree_resolution`, `format`, `face_count`, `texture`, "
        "`remove_background`) are shared across all modes."
    ),
)
async def submit_unified_job(
    request: GenerationRequest,
    manager: ManagerDep,
) -> JobResponse:
    """Submit a generation job using the unified request schema."""
    uid = await manager.submit_unified(request, SAVE_DIR)
    return manager.get_job(uid)  # type: ignore[return-value]


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Modes, models, presets and limits",
    description=(
        "Static + dynamic server state used by the UI to enable/disable "
        "tabs, preselect presets and validate uploads before submitting. "
        "Auth-gated like every other `/v1/*` route."
    ),
)
async def capabilities(manager: ManagerDep) -> CapabilitiesResponse:
    """Snapshot of what the server can do right now."""
    snap = manager.capabilities()
    snap["version"] = __version__
    return CapabilitiesResponse(**snap)


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------


@router.post(
    "/models/load",
    response_model=ModelLoadResponse,
    summary="Trigger a model warm-up (download + load weights into VRAM)",
    responses={
        202: {"description": "Warm-up started; poll ``/v1/models/status``"},
        409: {"description": "A load is already in progress"},
    },
)
async def start_model_load(manager: ManagerDep) -> ModelLoadResponse:
    """Kick off the inference model load in the background.

    The endpoint returns 202 immediately. The actual download +
    weight load happens on the inference worker thread; use
    ``GET /v1/models/status`` to track progress (or just submit a
    job once the System page shows ``loaded: true``).

    If the model is already loaded, this is a no-op and returns
    the same shape with ``status="already_loaded"``.
    """
    from hy3dgen.api.timeutils import utc_now

    # When the manager is delegating to an InferenceService, the
    # worker lives there. The service exposes a tiny ``warmup``
    # coroutine; we invoke it so the load actually goes through the
    # right worker.
    service = manager.inference_service
    if service is not None:
        status = await service.warmup()
    else:
        status = manager.warmup_model()

    if status == "already_loaded":
        return ModelLoadResponse(
            status="already_loaded",
            model=service.model_path if service is not None else manager.model_path,
            started_at=utc_now(),
        )
    return ModelLoadResponse(
        status=status,
        model=service.model_path if service is not None else manager.model_path,
        started_at=utc_now(),
    )


@router.get(
    "/models/status",
    response_model=ModelStatusResponse,
    summary="Current state of the inference model",
)
async def get_model_status(manager: ManagerDep) -> ModelStatusResponse:
    """Return whether the shape model is loaded and where the load is.

    ``loaded`` flips to ``true`` once ``ModelWorker.generate`` has
    materialised the shape pipeline (which is what
    ``POST /v1/models/load`` triggers eagerly).
    """

    # The worker may live on the manager (legacy) or on the
    # InferenceService (preferred). Check both so the status is
    # accurate regardless of which path the deployment uses.
    worker = manager.worker
    service = manager.inference_service
    if service is not None and getattr(service, "_worker", None) is not None:
        worker = service._worker
    model_path = service.model_path if service is not None else manager.model_path
    subfolder = (
        service.model_subfolder if service is not None else manager.model_subfolder
    )
    device = service.device if service is not None else manager.device
    pipeline = getattr(worker, "pipeline", None) if worker is not None else None
    last_error = manager.last_error
    if service is not None and service.last_error is not None:
        last_error = service.last_error
    return ModelStatusResponse(
        loaded=pipeline is not None,
        loading=False,  # reserved for future streaming progress
        model=model_path,
        subfolder=subfolder,
        device=device,
        last_error=last_error,
    )


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/jobs",
    response_model=list[JobResponse],
    summary="List all jobs currently in memory",
)
async def list_jobs(
    manager: ManagerDep,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
) -> list[JobResponse]:
    """List jobs in memory (most recent first).

    Pagination is offset-based for simplicity (the in-memory history
    is bounded by ``max_history`` so cursors are not strictly
    required). ``status`` filters by status name (``queued``,
    ``processing``, ``completed``, ``failed``, ``cancelled``) and
    ``q`` performs a case-insensitive substring search across
    ``uid``, ``request_type`` and the stored request payload.
    """
    items = sorted(
        manager.jobs.values(),
        key=lambda j: j.created_at or "",
        reverse=True,
    )
    if status:
        items = [j for j in items if j.status.value == status]
    if q:
        needle = q.lower()
        items = [
            j
            for j in items
            if needle in (j.uid or "").lower()
            or needle in (j.request_type or "").lower()
        ]
    if offset < 0:
        offset = 0
    if limit <= 0 or limit > 200:
        limit = 50
    return items[offset : offset + limit]


@router.get(
    "/library",
    response_model=LibraryResponse,
    summary="Paginated library of jobs (memory + store)",
)
async def library(
    manager: ManagerDep,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
) -> LibraryResponse:
    """Paginated library view used by the front-end LibraryPage.

    Combines the in-memory history and the SQLite store so the
    library survives a server restart. ``page`` is 1-indexed;
    ``page_size`` is clamped to ``[1, 100]``. The ``total`` count
    is approximated for performance: capped at ``max_history`` to keep
    the SQL query under a page.
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    offset = (page - 1) * page_size
    # Prefer the persistent store when available; otherwise fall back
    # to in-memory listing so dev mode (no SQLite) still has a working
    # library.
    if manager.store is not None:
        # Apply the same filter the items query uses so ``total`` is
        # the count of filtered records, not the unfiltered total.
        status_enum = JobStatus(status) if status else None
        items = await manager.store.list(
            status=status_enum,
            limit=page_size,
            offset=offset,
            q=q,
        )
        total = await manager.store.count_filtered(status=status_enum, q=q)
    else:
        all_items = sorted(
            manager.jobs.values(),
            key=lambda j: j.created_at or "",
            reverse=True,
        )
        if status:
            all_items = [j for j in all_items if j.status.value == status]
        if q:
            needle = q.lower()
            all_items = [
                j
                for j in all_items
                if needle in (j.uid or "").lower()
                or needle in (j.request_type or "").lower()
            ]
        total = len(all_items)
        items = all_items[offset : offset + page_size]
    return LibraryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total,
    )


# ---------------------------------------------------------------------------
# Real-time endpoints (SSE).
# IMPORTANT: registered BEFORE /jobs/{uid} so the literal paths
# (/jobs/events, /jobs/{uid}/events) win over the catch-all. FastAPI/
# Starlette match in registration order, not by path specificity, so
# this ordering is load-bearing.
# ---------------------------------------------------------------------------
@router.get("/jobs/events", summary="SSE stream of the full job list")
async def stream_jobs_events(
    request: Request,
    manager: ManagerDep,
) -> EventSourceResponse:
    """Server-Sent Events stream of the full job list.

    The first event is the current snapshot (sorted by created_at desc),
    so a client that connects after jobs have already been created
    still gets the latest state. Subsequent events are full snapshots
    whenever any job transitions, or when a job is added/evicted. The
    stream stays open until the client disconnects.
    """
    queue = manager.subscribe_list()

    async def list_publisher() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    jobs: list[JobResponse] = await asyncio.wait_for(
                        queue.get(),
                        timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    # Keep-alive ping so proxies don't time out the connection.
                    yield {"event": "ping", "data": "{}"}
                    continue
                # Slim payload: drop defaults and None so the wire format
                # only carries fields the UI cares about.
                payload = json.dumps(
                    [
                        j.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
                        for j in jobs
                    ],
                    default=str,
                )
                yield {"event": "list", "data": payload}
        finally:
            manager.unsubscribe_list(queue)

    return EventSourceResponse(list_publisher())


@router.get(
    "/jobs/{uid}/events",
    summary="SSE stream of a single job's transitions",
    responses={404: {"description": "Job not found"}},
)
async def stream_job_events(
    uid: str,
    request: Request,
    manager: ManagerDep,
) -> EventSourceResponse:
    """Server-Sent Events stream of job state changes.

    The first event is the current state, so a client that connects after
    a job has already started still gets the latest status. Subsequent
    events are sent whenever the job transitions to a new state. The
    stream closes after a terminal status (completed/failed/cancelled)
    is sent, or when the client disconnects.
    """
    # 404 if the uid is unknown.
    if manager.get_job(uid) is None:
        if manager.store is None:
            raise HTTPException(status_code=404, detail="Job not found")
        stored = await manager.store.get(uid)
        if stored is None:
            raise HTTPException(status_code=404, detail="Job not found")

    queue = await manager.subscribe(uid)

    async def event_publisher() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    job: JobResponse = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                payload = job.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
                yield {
                    "event": "status",
                    "id": job.uid,
                    "data": json.dumps(payload, default=str),
                }
                if job.status.value in _TERMINAL_STATUSES:
                    break
        finally:
            manager.unsubscribe(uid, queue)

    return EventSourceResponse(event_publisher())


@router.get(
    "/jobs/{uid}",
    response_model=JobResponse,
    responses={404: {"description": "Job not found"}},
)
async def get_job_status(uid: str, manager: ManagerDep) -> JobResponse:
    """Retrieve job status and result path."""
    job = manager.get_job(uid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{uid}")
async def cancel_job(uid: str, manager: ManagerDep) -> dict:
    """Request job cancellation. Idempotent — unknown uids return ok."""
    job = manager.get_job(uid)
    if job is not None and job.status.value == "processing":
        raise HTTPException(status_code=409, detail="A job already processing cannot be cancelled.")
    await manager.cancel_job(uid)
    return {"status": "cancellation_requested", "uid": uid}


# ---------------------------------------------------------------------------
# Signed file URLs
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{uid}/download-url",
    response_model=SignedFileResponse,
    summary="Mint a short-lived signed URL for the job's mesh output",
    responses={
        404: {"description": "Job has no file yet"},
        503: {"description": "URL signing is disabled (no key configured)"},
    },
)
async def get_signed_download_url(
    uid: str,
    manager: ManagerDep,
    request: Request,
    ttl_seconds: int = 3600,
) -> SignedFileResponse:
    """Mint an HMAC-signed ``/files/<name>.glb`` URL.

    The token is bound to the file's basename, scoped to a TTL (default
    1 h, capped at 24 h), and verifiable by ``_AuthStaticFiles``
    without leaking ``ARCHEON_API_KEY``. Falls back to 503 when no
    signing key is configured so callers know to use the legacy
    header-based path instead.
    """
    job = manager.get_job(uid)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.file_path:
        raise HTTPException(status_code=404, detail="Job has no file yet")
    # Build the public base URL from the incoming request so URLs work
    # behind reverse proxies (X-Forwarded-* handled by uvicorn config).
    base = str(request.base_url).rstrip("/")
    signed = signed_urls.build_signed_url(
        Path(job.file_path).name,
        ttl_seconds=ttl_seconds,
        base_url=base,
    )
    if signed is None:
        raise HTTPException(
            status_code=503,
            detail="Signed URLs are disabled (no signing key configured).",
        )
    return SignedFileResponse(
        url=signed,
        expires_at=int(time.time()) + min(ttl_seconds, signed_urls.MAX_TTL_SECONDS),
        ttl_seconds=min(ttl_seconds, signed_urls.MAX_TTL_SECONDS),
    )


# ---------------------------------------------------------------------------
# System + post-processing
# ---------------------------------------------------------------------------


@router.get(
    "/admin/stats",
    tags=["admin"],
    summary="Operational stats (job counts per status, model + queue state)",
)
async def admin_stats(manager: ManagerDep) -> dict:
    """Counts of jobs by status, plus the queue depth and persistence state.

    Useful for dashboards and health checks that want more detail
    than ``/health``. Auth-gated like every other ``/v1/*`` route.
    """
    jobs_in_memory = len(manager.jobs)
    counts_by_status: dict[str, int] = {}
    for j in manager.jobs.values():
        key = j.status.value if hasattr(j.status, "value") else str(j.status)
        counts_by_status[key] = counts_by_status.get(key, 0) + 1
    jobs_in_store = (await manager.store.count()) if manager.store is not None else 0
    return {
        "queue_depth": manager.queue.qsize(),
        "jobs_in_memory": jobs_in_memory,
        "jobs_in_store": jobs_in_store,
        "by_status": counts_by_status,
        "persistence_enabled": manager.store is not None,
        "model_loaded": manager.worker is not None,
        "max_history": manager.max_history,
    }


@router.get("/system/metrics", tags=["system"], summary="CPU/GPU/RAM usage")
async def get_metrics(manager: ManagerDep) -> dict:
    """Get system resource usage (CPU, GPU, RAM)."""
    metrics: dict = await asyncio.to_thread(get_system_metrics)
    metrics.update(
        jobs_in_memory=len(manager.jobs),
        jobs_in_store=await manager.store.count() if manager.store else 0,
        persistence_enabled=manager.store is not None,
    )
    return metrics


@router.post(
    "/meshops/process",
    summary="Decimate, convert or separate an existing job's mesh",
    responses={
        404: {"description": "Source job or its mesh not found"},
        500: {"description": "Mesh processing failed"},
    },
)
async def process_mesh(
    request: MeshOpsRequest,
    manager: ManagerDep,
    processor: MeshProcessorDep,
) -> dict:
    """Process an existing job's output mesh.

    Supported actions:

    * ``decimate``  - reduce face count
    * ``convert``   - re-encode (format conversion only)
    * ``separate``  - split the mesh into connected components and
      return a multi-body GLB/OBJ (Meshy/Hi3D "Auto-Separate Parts"
      equivalent). The response includes a ``parts`` array with the
      name and face count of every component so the UI can render a
      list.
    """
    job = manager.get_job(request.job_uid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.file_path or not Path(job.file_path).exists():  # noqa: ASYNC240
        raise HTTPException(status_code=404, detail="Job result file not found")

    base_name = Path(job.file_path).stem
    if request.action == "decimate":
        suffix = f"_decimate_{request.ratio:.2f}"
    elif request.action == "separate":
        suffix = "_separate"
    else:
        suffix = f"_{request.action}"
    output_path = str(Path(SAVE_DIR) / f"{base_name}{suffix}.{request.format}")

    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            None,
            processor.process,
            job.file_path,
            output_path,
            request.action,
            request.model_dump(),
        )
        response: dict = {"file_path": path}
        # When separating, surface a part list so the UI can render a
        # checklist without having to re-parse the GLB.
        if request.action == "separate":
            response["parts"] = _list_separated_parts(path)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _list_separated_parts(path: str) -> list[dict]:
    """Return a lightweight inventory of every node in a multi-body GLB.

    Each entry carries the node ``name``, ``face_count`` and a
    ``vertex_count`` so the UI can size the chips without re-loading
    the mesh. Designed to never raise: the endpoint still returns
    ``file_path`` on success even if part introspection fails.
    """
    try:
        import trimesh

        scene = trimesh.load(path, force="scene")
    except Exception:
        return []
    parts: list[dict] = []
    try:
        for name, geom in scene.geometry.items():
            face_count = len(getattr(geom, "faces", []))
            vertex_count = len(getattr(geom, "vertices", []))
            parts.append(
                {
                    "name": name,
                    "face_count": face_count,
                    "vertex_count": vertex_count,
                }
            )
    except Exception:
        return parts
    # Largest part first so the UI's default ordering matches Meshy.
    parts.sort(key=lambda p: p["face_count"], reverse=True)
    return parts
