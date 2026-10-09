"""Same as hy3dgen.api.server but with the worker disabled (idle loop).

Listens on POLYFORGE_PORT (default 8765). Used by the demo and the
stress-test suite (which override POLYFORGE_PORT to avoid clashing with
the real backend).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# The stress tests pass every relevant env var explicitly (POLYFORGE_JOB_DB,
# POLYFORGE_PORT, etc.) so we deliberately do NOT opt back in to .env
# loading here. A stray .env in the working directory must not override
# the test's environment.

import asyncio
import hy3dgen.api.manager as _mgr


async def _idle(self):  # type: ignore[no-redef]
    while True:
        await asyncio.sleep(3600)


async def _idle_svc_run(self):  # type: ignore[no-redef]
    # Drain the queue without executing anything: keep ``_queue.task_done``
    # in sync so the queue doesn't grow unbounded, but never call
    # ``_execute``. This is the equivalent of an idle worker for the
    # shared ``InferenceService`` path.
    while not self._shutdown.is_set():
        job = await self._queue.get()
        if job is None:
            self._queue.task_done()
            break
        try:
            # Mark the job as failed so consumers see it didn't run.
            self._publish(
                __import__(
                    "hy3dgen.api.inference_service", fromlist=["InferenceEvent"]
                ).InferenceEvent(
                    uid=job.uid,
                    stage=__import__(
                        "hy3dgen.api.inference_service", fromlist=["JobStage"]
                    ).JobStage.CANCELLED,
                    error="Patched server: worker disabled.",
                    request_type=job.request_type,
                )
            )
        finally:
            self._queue.task_done()


# Patch both the legacy and the shared-inference worker entry points.
_mgr.PriorityRequestManager._process_queue = _idle
try:
    import hy3dgen.api.inference_service as _svc

    _svc.InferenceService._run = _idle_svc_run
except Exception:  # pragma: no cover - older releases don't have the module
    pass

from hy3dgen.api.server import app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("POLYFORGE_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
