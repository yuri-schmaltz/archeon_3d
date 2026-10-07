"""Pytest fixtures for stress tests that need a live server + seeded data."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DB = "/tmp/polyforge-stress.db"


@pytest.fixture(autouse=True)
def _restore_api_settings():
    """Rebuild the API Settings singleton after every test.

    Several legacy tests ``importlib.reload(hy3dgen.api.config)`` with
    monkeypatched env vars, which permanently replaces
    ``config.settings`` for later tests. Reconstructing it here keeps
    Settings-backed behaviour hermetic without touching those tests.
    """
    from hy3dgen.api import config as config_module

    original_hf_home = os.environ.get("HF_HOME")
    yield
    config_module.settings = config_module.Settings(_env_file=None)
    if original_hf_home is None:
        os.environ.pop("HF_HOME", None)
    else:
        os.environ["HF_HOME"] = original_hf_home


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        try:
            r = requests.get(f"{url}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


@pytest.fixture(scope="session")
def _running_server():
    """Boot a patched server (no worker) on port 8766 with a 1000-job DB.

    Yields the base URL. Tears down the process afterwards.
    """
    import json
    import random
    import sqlite3
    import uuid
    from datetime import datetime, timedelta, timezone

    # Wipe any old DB
    if os.path.exists(DEMO_DB):
        os.unlink(DEMO_DB)
    if os.path.exists(DEMO_DB + "-wal"):
        os.unlink(DEMO_DB + "-wal")
    if os.path.exists(DEMO_DB + "-shm"):
        os.unlink(DEMO_DB + "-shm")

    # Bootstrap the schema
    import hy3dgen.api.persistence

    hy3dgen.api.persistence.JobStore(DEMO_DB)

    # Seed 1000 jobs
    db = sqlite3.connect(DEMO_DB)
    random.seed(42)
    statuses = (
        ["completed"] * 250
        + ["failed"] * 350
        + ["queued"] * 150
        + ["processing"] * 100
        + ["cancelled"] * 150
    )
    random.shuffle(statuses)
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(1000):
        status = statuses[i]
        age = random.randint(0, 86400)
        created = (now - timedelta(seconds=age)).isoformat()
        if status == "completed":
            completed = (now - timedelta(seconds=max(0, age - 12))).isoformat()
            file_path = f"/tmp/fake_{i % 20}.glb"
            error = None
        elif status == "cancelled":
            completed = (now - timedelta(seconds=max(0, age - 8))).isoformat()
            file_path = None
            error = "Cancelled"
        elif status == "failed":
            completed = (now - timedelta(seconds=max(0, age - 4))).isoformat()
            file_path = None
            error = "fake error"
        else:
            completed = None
            file_path = None
            error = None
        uid = str(uuid.uuid4())
        payload = json.dumps({"text": f"job {i}", "steps": 50, "guidance": 5.0, "seed": i})
        rows.append((uid, status, created, completed, file_path, error, payload))
    db.executemany(
        "INSERT INTO jobs (uid, status, created_at, completed_at, file_path, error, request_blob) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()

    # Start the patched server on port 8766
    env = os.environ.copy()
    env["POLYFORGE_JOB_DB"] = DEMO_DB
    env["POLYFORGE_HOST"] = "127.0.0.1"
    env["POLYFORGE_PORT"] = "8766"
    env["POLYFORGE_LOG_LEVEL"] = "error"
    env["POLYFORGE_RATE_LIMIT"] = "false"
    env["PYTHONPATH"] = str(REPO_ROOT)

    proc = subprocess.Popen(
        [sys.executable, "docs/demo/server_patched.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base = "http://127.0.0.1:8766"
    if not _wait_for_server(base):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"server did not come up on {base}")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def _seeded_job(_running_server):
    """Return a valid completed job uid for per-job tests."""
    r = requests.get(f"{_running_server}/v1/jobs?status=completed", timeout=5)
    # The demo API doesn't filter, so just take the first completed one
    for j in r.json():
        if j["status"] == "completed" and j.get("file_path"):
            return j["uid"]
    pytest.skip("no completed jobs in seed")
