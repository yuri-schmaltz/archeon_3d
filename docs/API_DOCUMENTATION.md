# Archeon 3D Backend — API Reference

Version `2.1.0.post7`. Generated from the OpenAPI schema by
`scripts/gen_api_docs.py`; do not edit by hand.

High-performance local 3D generation backend with priority queuing and polymorphic API.

## Contents

- [Authentication](#authentication)
- [Probes and metrics](#probes-and-metrics)
- [Endpoints](#endpoints)

17 operations across 15 paths.

## Authentication

When `ARCHEON_API_KEY` is set, every `/v1/*` route requires an `X-API-Key`
header. A missing header returns `401` with `WWW-Authenticate: ApiKey`; a
wrong key returns `403`. With no key configured, auth is disabled (dev only).

`/health`, `/ready`, `/metrics` and the frontend assets are always open.

`/files/**` accepts either the API key or an HMAC-signed token from
`GET /v1/jobs/{uid}/download-url`.

## Probes and metrics

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health Check |
| `GET` | `/ready` | Readiness Check |
| `GET` | `/metrics` | Prometheus metrics in text format (excluded from the schema). |

`/health` is a **liveness** probe: it answers `200` as soon as the process is
up and reports a `ready` boolean. `/ready` is the **readiness** gate: it
returns `503` until the job store has been rehydrated into memory, so a load
balancer can hold traffic until the in-memory job view matches the store.

## Endpoints

### `GET /health`

Health Check

Liveness + readiness probe. Returns 200 with a body that includes: `status`: `"ok"` if the server is up (even if the model has not loaded yet). `ready`: `False` while the initial job-store rehydrate is still running. Use `/ready` when you need a readiness gate. `version`: server version. `model_loaded`: whether the inference worker has been initialized. `queue_size`: how many jobs are pending in the priority queue. `jobs_in_memory` / `jobs_in_store`: how many jobs the manager knows about in each layer (the two numbers can differ briefly during rehydrate). `persistence_enabled`: whether SQLite-backed persistence is on. `auth_required`: whether X-API-Key is enforced on /v1/*. `last_error`: the most recent worker error, if any. Cleared on success. `uptime_seconds`: seconds since this process started. `capabilities`: feature flags (SSE endpoints live, etc.).

Responses: `200`

### `GET /ready`

Readiness Check

Readiness probe. Unlike `/health` this returns 503 until the initial job-store rehydrate has completed, so a load balancer or orchestrator can hold traffic until the in-memory job view is consistent with the persistent store.

Responses: `200`

### `GET /v1/admin/stats`

Operational stats (job counts per status, model + queue state)

Counts of jobs by status, plus the queue depth and persistence state. Useful for dashboards and health checks that want more detail than `/health`. Auth-gated like every other `/v1/*` route.

Responses: `200`, `422`

### `GET /v1/capabilities`

Modes, models, presets and limits

Static + dynamic server state used by the UI to enable/disable tabs, preselect presets and validate uploads before submitting. Auth-gated like every other `/v1/*` route.

Responses: `200`, `422`

### `POST /v1/generate`

Submit a unified generation job

All input fields are optional at the type level; the backend infers the generation mode from what's filled in. See `GenerationRequest` for the dispatch rules. Common params (`seed`, `steps`, `guidance`, `octree_resolution`, `format`, `face_count`, `texture`, `remove_background`) are shared across all modes.

Responses: `202`, `422`

**Body**

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `text` | str | — | Text prompt or guidance. Required for text_to_3d. |
| `image` | str | — | Base64-encoded image (single view, used by image_to_3d). |
| `views` | str | — | Four base64-encoded views (front/back/left/right). |
| `mesh` | str | — | Base64-encoded GLB to re-texture (texture_mesh). |
| `seed` | int | `1234` | Random seed |
| `steps` | 1-100 | `50` | Denoising steps |
| `guidance` | 1-20 | `5.0` | Guidance scale |
| `octree_resolution` | 16-512 | `256` | Voxel resolution |
| `format` | `glb` \| `obj` \| `ply` \| `stl` | `'glb'` | Output mesh format |
| `texture` | bool | `False` | Generate texture? (Honoured for text_to_3d / image_to_3d; forced on for texture_mesh.) |
| `face_count` | 100-1e+06 | `40000` | Target face count for reduction |
| `remove_background` | bool | `True` | Remove background using rembg? (image_to_3d only.) |

### `POST /v1/jobs`

Submit a generation job (legacy polymorphic)

Accepts the discriminated-union body `{ "type": "text_to_3d" | "image_to_3d" | "multiview" | "texture_mesh", ... }`. New code should use `POST /v1/generate` instead — the unified schema infers the mode from the fields you fill in.

Responses: `202`, `422`

### `GET /v1/jobs`

List all jobs currently in memory

List jobs in memory (most recent first). Pagination is offset-based for simplicity (the in-memory history is bounded by `max_history` so cursors are not strictly required). `status` filters by status name (`queued`, `processing`, `completed`, `failed`, `cancelled`) and `q` performs a case-insensitive substring search across `uid`, `request_type` and the stored request payload.

Responses: `200`, `422`

**Query parameters**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `limit` | int | `50` |  |
| `offset` | int | `0` |  |
| `status` | str | — |  |
| `q` | str | — |  |

### `GET /v1/jobs/events`

SSE stream of the full job list

Server-Sent Events stream of the full job list. The first event is the current snapshot (sorted by created_at desc), so a client that connects after jobs have already been created still gets the latest state. Subsequent events are full snapshots whenever any job transitions, or when a job is added/evicted. The stream stays open until the client disconnects.

Responses: `200`, `422`

### `GET /v1/jobs/{uid}`

Get Job Status

Retrieve job status and result path.

Responses: `200`, `404`, `422`

### `DELETE /v1/jobs/{uid}`

Cancel Job

Request job cancellation. Idempotent — unknown uids return ok.

Responses: `200`, `422`

### `GET /v1/jobs/{uid}/download-url`

Mint a short-lived signed URL for the job's mesh output

Mint an HMAC-signed `/files/<name>.glb` URL. The token is bound to the file's basename, scoped to a TTL (default 1 h, capped at 24 h), and verifiable by `_AuthStaticFiles` without leaking `ARCHEON_API_KEY`. Falls back to 503 when no signing key is configured so callers know to use the legacy header-based path instead.

Responses: `200`, `404`, `422`, `503`

**Query parameters**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `ttl_seconds` | int | `3600` |  |

### `GET /v1/jobs/{uid}/events`

SSE stream of a single job's transitions

Server-Sent Events stream of job state changes. The first event is the current state, so a client that connects after a job has already started still gets the latest status. Subsequent events are sent whenever the job transitions to a new state. The stream closes after a terminal status (completed/failed/cancelled) is sent, or when the client disconnects.

Responses: `200`, `404`, `422`

### `GET /v1/library`

Paginated library of jobs (memory + store)

Paginated library view used by the front-end LibraryPage. Combines the in-memory history and the SQLite store so the library survives a server restart. `page` is 1-indexed; `page_size` is clamped to `[1, 100]`. The `total` count is approximated for performance: capped at `max_history` to keep the SQL query under a page.

Responses: `200`, `422`

**Query parameters**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `page` | int | `1` |  |
| `page_size` | int | `20` |  |
| `status` | str | — |  |
| `q` | str | — |  |

### `POST /v1/meshops/process`

Decimate, convert or separate an existing job's mesh

Process an existing job's output mesh. Supported actions: `decimate`  - reduce face count `convert`   - re-encode (format conversion only) `separate`  - split the mesh into connected components and return a multi-body GLB/OBJ (Meshy/Hi3D "Auto-Separate Parts" equivalent). The response includes a `parts` array with the name and face count of every component so the UI can render a list.

Responses: `200`, `404`, `422`, `500`

**Body**

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `job_uid` | str | required | UID of the source job to operate on |
| `action` | str | required | Mesh operation to apply |
| `format` | `glb` \| `obj` \| `ply` \| `stl` | `'glb'` | Output mesh format |
| `ratio` | 0.01-1 | `0.5` | For decimate: target ratio of faces to keep |
| `min_face_count` | ≥ 10 | `500` | For separate: discard components with fewer faces than this (filters marching-cubes noise). |
| `only_watertight` | bool | `False` | For separate: keep only watertight components (recommended for 3D-printing workflows). |
| `repair` | bool | `True` | For separate: try to fill small holes in each component before checking watertightness. |
| `min_volume_ratio` | 0-1 | `0.0` | For separate: discard components whose volume is smaller than this fraction of the largest component (0 disables). |

### `POST /v1/models/load`

Trigger a model warm-up (download + load weights into VRAM)

Kick off the inference model load in the background. The endpoint returns 202 immediately. The actual download + weight load happens on the inference worker thread; use `GET /v1/models/status` to track progress (or just submit a job once the System page shows `loaded: true`). If the model is already loaded, this is a no-op and returns the same shape with `status="already_loaded"`.

Responses: `200`, `202`, `409`, `422`

### `GET /v1/models/status`

Current state of the inference model

Return whether the shape model is loaded and where the load is. `loaded` flips to `true` once `ModelWorker.generate` has materialised the shape pipeline (which is what `POST /v1/models/load` triggers eagerly).

Responses: `200`, `422`

### `GET /v1/system/metrics`

CPU/GPU/RAM usage

Get system resource usage (CPU, GPU, RAM).

Responses: `200`, `422`

## Notes

- Two endpoints stream Server-Sent Events: `/v1/jobs/events` for the whole
  list and `/v1/jobs/{uid}/events` for a single job. Both close on a
  terminal status (`completed`, `failed`, `cancelled`).
- `/v1/jobs` is paginated (`limit` caps at 200). Use `/v1/library` to page
  through the full history, which reads from SQLite and survives restarts.
- Only one uvicorn worker is supported: inference is serialised through a
  single in-process queue on one GPU. Run one process per GPU.
- SSE streams must be declared before `/v1/jobs/{uid}` in the route table or
  the literal path would be captured by the parameter.
