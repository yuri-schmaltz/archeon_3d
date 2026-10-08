import hmac
import ipaddress
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Receive, Scope, Send

from hy3dgen.api import auth as _auth_module, signed_urls as _signed_urls
from hy3dgen.api.auth import require_api_key
from hy3dgen.api.config import (
    SAVE_DIR,
    configure_logging,
    get_bind_host,
    get_bind_port,
    get_cors_origins,
    get_job_db_path,
    settings,
)
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.metrics import render_metrics
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.routes import router
from hy3dgen.meshops.processor import MeshProcessor
from hy3dgen.version import __version__

logger = logging.getLogger("hy3dgen.api.server")


def _require_auth_for_non_loopback(host: str | None = None) -> None:
    """Prevent accidentally exposing an unauthenticated API on the network."""
    bind_host = (host or get_bind_host()).strip().lower()
    try:
        is_loopback = ipaddress.ip_address(bind_host).is_loopback
    except ValueError:
        is_loopback = bind_host == "localhost"
    if not is_loopback and _auth_module.get_api_key() is None:
        raise RuntimeError(
            "POLYFORGE_API_KEY is required when the API binds to a non-loopback host."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle (start/stop background workers)."""
    _require_auth_for_non_loopback()
    configure_logging()
    logger.info("PolyForge API starting on %s:%s", get_bind_host(), get_bind_port())
    # Initialize the persistent store (or None to disable).
    db_path = get_job_db_path()
    store = JobStore(db_path) if db_path else None
    if store is not None:
        logger.info("JobStore initialized at %s", db_path)

    # Initialize manager with optional store, then start the worker loop.
    # ``start()`` rehydrates from the store before kicking off the
    # processing task, so jobs that were mid-flight when the process
    # died are recovered.
    from hy3dgen.api.inference_service import InferenceService

    service: InferenceService | None = None
    if settings.use_shared_inference:
        service = InferenceService(
            device=settings.device,
            max_queue_size=settings.max_queue_size,
            save_dir=SAVE_DIR,
            model_path=settings.model,
            model_subfolder=settings.model_subfolder,
            multiview_model=settings.multiview_model,
            multiview_subfolder=settings.multiview_subfolder,
            t2i_model=settings.t2i_model,
        )
    app.state.inference_service = service
    app.state.manager = PriorityRequestManager(
        device=settings.device,
        max_history=settings.max_history,
        max_queue_size=settings.max_queue_size,
        max_age_seconds=settings.max_age_seconds,
        model_path=settings.model,
        model_subfolder=settings.model_subfolder,
        multiview_model=settings.multiview_model,
        multiview_subfolder=settings.multiview_subfolder,
        t2i_model=settings.t2i_model,
        store=store,
        inference_service=service,
    )
    # ``await_rehydrate=False`` keeps startup fast: the job store is
    # restored in the background so a large history does not delay the
    # first request. ``/health`` answers immediately; ``/ready`` stays 503
    # until the in-memory job view matches the store.
    await app.state.manager.start(await_rehydrate=False)

    # Initialize processor
    app.state.mesh_processor = MeshProcessor()

    try:
        yield
    finally:
        await app.state.manager.stop()


limiter = Limiter(
    key_func=get_remote_address,
    # slowapi rejects an empty ``default_limits`` entry, so fall back to
    # "no limit" explicitly when the operator opts out.
    default_limits=[settings.rate_limit] if settings.rate_limit else [],
)

app = FastAPI(
    title="PolyForge Backend",
    description="High-performance local 3D generation backend — do prompt ao polígono. Priority queuing + polymorphic API.",
    version=__version__,
    lifespan=lifespan,
)

# CORS: spec-compliant. When origins == ['*'] we must disable credentials
# (browsers reject the combination). For real deployments, set
# POLYFORGE_CORS_ORIGINS to a comma-separated
# allow-list and optionally POLYFORGE_ALLOW_CREDENTIALS=true.
_cors_origins = get_cors_origins()
# ``*`` + credentials is rejected by browsers, so force it off in that case.
_cors_allow_credentials = settings.allow_credentials and _cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# /health stays unauthenticated so load balancers / the launcher can probe it
# without needing the API key.
@app.get("/health")
async def health_check():
    """Liveness + readiness probe.

    Returns 200 with a body that includes:
    - ``status``: ``"ok"`` if the server is up (even if the model has not loaded yet).
    - ``ready``: ``False`` while the initial job-store rehydrate is still
      running. Use ``/ready`` when you need a readiness gate.
    - ``version``: server version.
    - ``model_loaded``: whether the inference worker has been initialized.
    - ``queue_size``: how many jobs are pending in the priority queue.
    - ``jobs_in_memory`` / ``jobs_in_store``: how many jobs the manager
      knows about in each layer (the two numbers can differ briefly
      during rehydrate).
    - ``persistence_enabled``: whether SQLite-backed persistence is on.
    - ``auth_required``: whether X-API-Key is enforced on /v1/*.
    - ``last_error``: the most recent worker error, if any. Cleared on success.
    - ``uptime_seconds``: seconds since this process started.
    - ``capabilities``: feature flags (SSE endpoints live, etc.).
    """
    import time

    manager = getattr(app.state, "manager", None)
    queue_size = manager.queue_depth if manager is not None else 0
    last_error = getattr(manager, "last_error", None) if manager is not None else None
    store = getattr(manager, "store", None) if manager is not None else None
    jobs_in_memory = len(manager.jobs) if manager is not None else 0
    jobs_in_store = (await store.count()) if store is not None else 0
    started = getattr(app.state, "started_at", None)
    if started is None:
        started = time.monotonic()
        app.state.started_at = started
    return {
        "status": "ok",
        "version": app.version,
        "model_loaded": manager is not None and manager.model_loaded,
        "queue_size": queue_size,
        "ready": manager is None or manager.ready,
        "jobs_in_memory": jobs_in_memory,
        "jobs_in_store": jobs_in_store,
        "persistence_enabled": store is not None,
        "auth_required": _auth_module.get_api_key() is not None,
        "last_error": last_error,
        "uptime_seconds": round(time.monotonic() - started, 1),
        "capabilities": {
            "unified_generate_endpoint": True,
            "sse_per_job": True,
            "sse_list": True,
        },
    }


@app.get("/ready")
async def readiness_check():
    """Readiness probe.

    Unlike ``/health`` this returns 503 until the initial job-store
    rehydrate has completed, so a load balancer or orchestrator can
    hold traffic until the in-memory job view is consistent with the
    persistent store.
    """
    manager = getattr(app.state, "manager", None)
    if manager is None:
        return {"status": "ready", "ready": True}
    ready = manager.ready
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "rehydrating",
            "ready": ready,
            "jobs_in_memory": len(manager.jobs),
        },
    )


# Make the limiter reachable from request handlers.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Health/readiness/metrics and the SPA shell are operational traffic, not API
# usage. Exempt them so monitoring and normal page loads cannot consume the
# per-IP API budget.
limiter.exempt(health_check)
limiter.exempt(readiness_check)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    """Prometheus text-format metrics. Excluded from the OpenAPI schema
    (it's an ops endpoint, not part of the public API contract)."""
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")


limiter.exempt(metrics_endpoint)


# Body size limit: bail out early if a request advertises a Content-Length
# over the configured cap (POLYFORGE_MAX_BODY_BYTES, default 64 MiB to match
# the nginx setting). Without this guard nginx (or the default uvicorn
# limit) would buffer an unbounded payload into a temp file before we
# even see the request, wasting resources and giving us a worse error
# message to surface.
_MAX_BODY_BYTES = settings.max_body_bytes or None


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int | None = None) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_body_bytes = self.max_body_bytes
        if max_body_bytes is None:
            max_body_bytes = _MAX_BODY_BYTES
        if max_body_bytes is None:
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for name, value in scope.get("headers", []) if name.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > max_body_bytes:
                    await Response(
                        content=f"Request body too large (>{max_body_bytes} bytes).",
                        status_code=413,
                    )(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await Response(
                content=f"Request body too large (>{max_body_bytes} bytes).",
                status_code=413,
            )(scope, receive, send)


app.add_middleware(RequestBodyLimitMiddleware)


class _AuthStaticFiles(StaticFiles):
    """StaticFiles subclass that enforces auth on file downloads.

    Two acceptance paths are supported:

    1. ``X-API-Key`` header (the classic path) — used by trusted
       clients (the launcher, scripts).
    2. Signed URL tokens (see ``signed_urls.py``) — used for sharing
       with untrusted clients without leaking the API key. A signed
       token is valid for ``ttl_seconds`` and is bound to a single
       path.

    When ``POLYFORGE_API_KEY`` is empty
    and no signing key is configured the check is a no-op (local dev).
    """

    async def get_response(self, path, scope):
        # Signed URLs take precedence — they're the only path that
        # doesn't require the caller to know the API key.
        query_string = scope.get("query_string", b"").decode("latin-1")
        if query_string and _signed_urls.verify_signed_url(path, query_string):
            return await super().get_response(path, scope)
        if _auth_module.get_api_key() is not None:
            # Headers arrive as raw bytes in the ASGI scope.
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            provided = headers.get("x-api-key", "")
            if not provided:
                return Response(
                    content="Missing X-API-Key header.",
                    status_code=401,
                    headers={"WWW-Authenticate": "ApiKey"},
                )
            if not hmac.compare_digest(provided, _auth_module.get_api_key() or ""):
                return Response(content="Invalid API key.", status_code=403)
        return await super().get_response(path, scope)


app.mount("/files", _AuthStaticFiles(directory=SAVE_DIR), name="files")

# Apply API-key auth to everything else (the routes registered below).
# /health is already registered above; FastAPI dependencies apply per-route.
# The router endpoints protect themselves with ``require_api_key``.
app.include_router(router, dependencies=[Depends(require_api_key)])


# Serve the compiled frontend (Vite ``dist/``) at the root URL so
# ``http://127.0.0.1:8081/`` is the actual UI, not a JSON 404.
#
# IMPORTANT: this block runs *after* ``app.include_router(router)``
# so the API routes are matched first. A catch-all registered before
# the API would shadow ``/v1/*`` and return 404 instead of routing
# the request to the API.
#
# The dist is optional: if the project was checked out without
# running ``npm run build`` we silently skip the mount and let the
# user get a useful JSON 404. The launcher always builds the
# frontend, so this only affects exotic deployments.
_BASE = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIST = _BASE / "polyforge_frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def _serve_index() -> FileResponse:
        """Serve the Vite ``index.html`` for the document root."""
        return FileResponse(_FRONTEND_DIST / "index.html")

    limiter.exempt(_serve_index)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_spa(full_path: str) -> Response:
        """Serve any non-API, non-asset path as a static file.

        This is the hash-router fallback: a refresh on
        ``/biblioteca`` would otherwise 404 because FastAPI has no
        route for it. We try the file system first (so direct asset
        hits like ``/favicon.svg`` work) and fall back to
        ``index.html`` so the SPA can take over.
        """
        # Path-traversal guard: only serve files inside dist/.
        candidate = (_FRONTEND_DIST / full_path).resolve()
        try:
            candidate.relative_to(_FRONTEND_DIST.resolve())
        except ValueError:
            return Response(status_code=404)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")

    limiter.exempt(_serve_spa)
else:
    logger.info(
        "Frontend dist/ not found at %s; root URL will return 404. "
        "Run 'cd polyforge_frontend && npm run build' to enable the UI.",
        _FRONTEND_DIST,
    )


def _reject_multi_worker(parser, workers: int) -> None:
    """Refuse ``workers > 1``.

    Inference is serialised through a single in-process priority queue and
    the model lives in one process's VRAM. Extra uvicorn workers would each
    hold their own queue and their own copy of the model, and would each
    rehydrate the same SQLite file independently. The supported way to use
    several GPUs is one process per GPU.
    """
    if workers != 1:
        parser.error(
            f"--workers {workers} is not supported. This backend serialises "
            "inference through a single in-process queue and shares one GPU; "
            "run one process per GPU instead."
        )


def main():
    """Console entry point declared in pyproject.toml: ``hy3dgen-api`` / ``polyforge-api``.

    CLI flags take precedence over the POLYFORGE_HOST / POLYFORGE_PORT env
    vars, which themselves default to ``127.0.0.1:8081``.
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="PolyForge Backend API server")
    parser.add_argument(
        "--port",
        type=int,
        default=get_bind_port(),
        help="Port to listen on (overrides POLYFORGE_PORT, default 8081).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=get_bind_host(),
        help="Bind host (overrides POLYFORGE_HOST, default 127.0.0.1).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=settings.workers,
        help=(
            "Number of uvicorn workers (overrides POLYFORGE_WORKERS). "
            "Only 1 is supported: each worker would own a separate "
            "inference queue, its own copy of the model in VRAM, and "
            "would rehydrate the same SQLite file independently."
        ),
    )
    args = parser.parse_args()
    _reject_multi_worker(parser, args.workers)
    uvicorn.run(
        "hy3dgen.api.server:app",
        host=args.host,
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()
