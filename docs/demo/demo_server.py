"""DEMO server for the screenshot — no worker, jobs stay in their stored state."""
import logging
import sys
sys.path.insert(0, "/workspace/my-hunyuan-3D/.worktrees/feature-ui")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import Limiter
from slowapi.util import get_remote_address

from hy3dgen.api.config import get_job_db_path, get_cors_origins
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.routes import router as api_router
from hy3dgen.meshops.processor import MeshProcessor

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("demo")
log.warning("DEMO PolyForge API starting")

@asynccontextmanager
async def lifespan(app):
    db_path = get_job_db_path()
    store = JobStore(db_path) if db_path else None
    app.state.manager = PriorityRequestManager(store=store)
    await app.state.manager.rehydrate()
    # Worker NOT started.
    app.state.mesh_processor = MeshProcessor()
    log.warning("DEMO worker idle — jobs will not be processed.")
    yield
    await app.state.manager.stop()

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app = FastAPI(title="PolyForge DEMO", version="1.0.1-demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "demo": True}

app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
