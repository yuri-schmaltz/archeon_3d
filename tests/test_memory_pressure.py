"""
Memory pressure test: 10k jobs in the SQLite store + a full rehydrate.

Inserts 10,000 jobs directly into the SQLite store, then starts a
patched server pointed at the DB and measures:
- Time to rehydrate 10k jobs
- Latency of /v1/jobs (one page) while the full 10k sit in memory
- That the whole history is still reachable through /v1/library
- Memory profile of the response (size on the wire)

Rehydration runs in the background, so the test gates on ``/ready``
rather than ``/health``.
"""
import asyncio
import json
import os
import random
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest


def _seed_10k(db_path: str):
    """Insert 10,000 jobs into a fresh SQLite store."""
    if os.path.exists(db_path):
        os.unlink(db_path)
    for ext in ("-wal", "-shm"):
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)

    import hy3dgen.api.persistence
    hy3dgen.api.persistence.JobStore(db_path)

    random.seed(123)
    db = sqlite3.connect(db_path)
    statuses = (
        ["completed"] * 2500
        + ["failed"] * 3500
        + ["queued"] * 1500
        + ["processing"] * 1000
        + ["cancelled"] * 1500
    )
    random.shuffle(statuses)
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(10_000):
        status = statuses[i]
        age = random.randint(0, 86400 * 30)
        created = (now - timedelta(seconds=age)).isoformat()
        if status == "completed":
            completed = (now - timedelta(seconds=max(0, age - 12))).isoformat()
            file_path = f"/tmp/fake_{i % 50}.glb"
            error = None
        elif status == "cancelled":
            completed = (now - timedelta(seconds=max(0, age - 8))).isoformat()
            file_path = None
            error = "Cancelled"
        elif status == "failed":
            completed = (now - timedelta(seconds=max(0, age - 4))).isoformat()
            file_path = None
            error = "simulated failure"
        else:
            completed = None
            file_path = None
            error = None
        uid = str(uuid.uuid4())
        payload = json.dumps({"text": f"job {i}", "steps": 50, "guidance": 5.0, "seed": i})
        rows.append((uid, status, created, completed, file_path, error, payload))

    db.execute("BEGIN")
    db.executemany(
        "INSERT INTO jobs (uid, status, created_at, completed_at, file_path, error, request_blob) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()


@pytest.fixture(scope="session")
def _10k_server():
    """Session-scoped fixture: seed a 10k-job DB and time a raw rehydrate."""
    db = "/tmp/archeon-10k.db"

    print("\n[10k seed] starting (this takes a few seconds)...")
    t0 = time.perf_counter()
    _seed_10k(db)
    seed_time = time.perf_counter() - t0
    print(f"[10k seed] inserted in {seed_time:.2f}s")

    # Raw restore_all() throughput, independent of the manager's
    # bookkeeping (the server path is covered by test_10k_list_endpoint).
    t0 = time.perf_counter()
    import hy3dgen.api.persistence

    store = hy3dgen.api.persistence.JobStore(db)
    count = 0

    async def _rehydrate():
        nonlocal count
        async for _job, _payload in store.restore_all():
            count += 1

    asyncio.run(_rehydrate())
    rehydrate_time = time.perf_counter() - t0
    print(f"[10k rehydrate] {count} jobs in {rehydrate_time*1000:.1f}ms "
          f"({count / rehydrate_time:.0f} jobs/s)")

    # Memory profile via RSS
    import os
    rss_mb = 0
    try:
        import psutil
        rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        pass

    yield {
        "db": db,
        "seed_time": seed_time,
        "rehydrate_time": rehydrate_time,
        "job_count": count,
        "rss_mb": rss_mb,
    }


async def test_10k_rehydrate_speed(_10k_server):
    """Rehydrating 10k jobs should complete in under 2 seconds."""
    info = _10k_server
    assert info["job_count"] == 10_000, f"expected 10k jobs, got {info['job_count']}"
    assert info["rehydrate_time"] < 2.0, (
        f"rehydrate took {info['rehydrate_time']:.2f}s, expected < 2s"
    )


async def test_10k_list_endpoint(_10k_server):
    """A full page of /v1/jobs should respond fast with 10k jobs loaded."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent

    env = os.environ.copy()
    env["ARCHEON_JOB_DB"] = _10k_server["db"]
    env["ARCHEON_HOST"] = "127.0.0.1"
    env["ARCHEON_PORT"] = "8767"
    env["ARCHEON_LOG_LEVEL"] = "error"
    env["ARCHEON_RATE_LIMIT"] = "false"
    env["PYTHONPATH"] = str(repo_root)

    proc = subprocess.Popen(
        [sys.executable, "docs/demo/server_patched.py"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to finish rehydrating. /health answers as
        # soon as the process is up (rehydration runs in the background),
        # so /ready is the gate that guarantees all 10k jobs are visible
        # to /v1/jobs before we time that endpoint.
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8767", timeout=60.0) as client:
            ready = False
            for _ in range(300):
                try:
                    r = await client.get("/ready")
                    if r.status_code == 200:
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.2)
            if not ready:
                pytest.fail("server did not become ready")

            # /v1/jobs is paginated (max 200 per page), so this measures the
            # worst case: a full page while 10k jobs sit in memory. The
            # complete 10k is verified through /v1/library's total.
            t0 = time.perf_counter()
            r = await client.get("/v1/jobs", params={"limit": 200, "offset": 0})
            elapsed = time.perf_counter() - t0
            assert r.status_code == 200
            data = r.json()
            size_kb = len(r.content) / 1024

            print(
                f"\n[10k list] GET /v1/jobs: {elapsed*1000:.0f}ms, "
                f"jobs={len(data)}, size={size_kb:.0f}KB"
            )

            assert len(data) == 200, f"expected a full page of 200, got {len(data)}"
            assert elapsed < 1.0, f"/v1/jobs took {elapsed:.2f}s with 10k jobs loaded"

            # The whole history is reachable: /library reports the full
            # count from the store without materialising every job.
            lib = await client.get("/v1/library", params={"page_size": 1})
            assert lib.status_code == 200
            assert lib.json()["total"] == 10_000
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
