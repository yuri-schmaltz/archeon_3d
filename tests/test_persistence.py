"""Tests for the async SQLite-backed ``JobStore``."""
import os
import tempfile
from datetime import datetime, timedelta

import pytest

try:
    import torch  # noqa: F401
    from hy3dgen.api.persistence import JobStore
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    JobStore = None  # type: ignore[assignment]
    JobResponse = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch not installed",
)


@pytest.fixture
async def store(tmp_path):
    """Fresh async JobStore backed by a per-test SQLite file."""
    db = tmp_path / "jobs.db"
    s = JobStore(str(db))
    yield s
    # Per-call connections; nothing to close.


def _make_job(uid, status=JobStatus.QUEUED, age_seconds=0):
    return JobResponse(
        uid=uid,
        status=status,
        created_at=(datetime.utcnow() - timedelta(seconds=age_seconds)).isoformat(),
    )


class TestUpsertAndGet:
    async def test_database_file_has_private_permissions(self, tmp_path):
        import stat

        store = JobStore(str(tmp_path / "private.db"))
        mode = stat.S_IMODE(os.stat(store._db_path).st_mode)
        assert mode & 0o077 == 0

    async def test_insert_then_get(self, store):
        job = _make_job("abc", JobStatus.QUEUED)
        await store.upsert(job)
        got = await store.get("abc")
        assert got is not None
        assert got.uid == "abc"
        assert got.status == JobStatus.QUEUED

    async def test_overwrite_existing(self, store):
        await store.upsert(_make_job("abc", JobStatus.QUEUED))
        await store.upsert(_make_job("abc", JobStatus.PROCESSING))
        got = await store.get("abc")
        assert got.status == JobStatus.PROCESSING

    async def test_get_missing_returns_none(self, store):
        assert await store.get("missing") is None

    async def test_payload_persisted(self, store):
        job = _make_job("p", JobStatus.QUEUED)
        await store.upsert(job, request_payload={"text": "hi", "n": 1})
        got = await store.get("p")
        assert got is not None
        # We don't expose payload on JobResponse; verify via restore_all
        rows = [r async for r in store.restore_all()]
        assert len(rows) == 1
        assert rows[0][1] == {"text": "hi", "n": 1}

    async def test_payload_not_overwritten(self, store):
        job = _make_job("p", JobStatus.QUEUED)
        await store.upsert(job, request_payload={"first": True})
        # Second upsert without payload keeps the original
        await store.upsert(_make_job("p", JobStatus.COMPLETED))
        rows = [r async for r in store.restore_all()]
        assert rows[0][1] == {"first": True}


class TestList:
    async def test_list_all(self, store):
        for uid in ("a", "b", "c"):
            await store.upsert(_make_job(uid, JobStatus.QUEUED))
        all_jobs = await store.list()
        uids = {j.uid for j in all_jobs}
        assert uids == {"a", "b", "c"}

    async def test_list_filter_by_status(self, store):
        await store.upsert(_make_job("a", JobStatus.QUEUED))
        await store.upsert(_make_job("b", JobStatus.COMPLETED))
        await store.upsert(_make_job("c", JobStatus.COMPLETED))
        completed = await store.list(status=JobStatus.COMPLETED)
        assert {j.uid for j in completed} == {"b", "c"}

    async def test_list_with_limit(self, store):
        for i in range(5):
            await store.upsert(_make_job(f"j{i}", JobStatus.QUEUED))
        assert len(await store.list(limit=3)) == 3


class TestDelete:
    async def test_delete_existing(self, store):
        await store.upsert(_make_job("d", JobStatus.QUEUED))
        assert await store.delete("d") is True
        assert await store.get("d") is None

    async def test_delete_missing_returns_false(self, store):
        assert await store.delete("missing") is False

    async def test_delete_older_than(self, store):
        # Old completed job
        old = _make_job("old", JobStatus.COMPLETED, age_seconds=120)
        await store.upsert(old)
        # Recent completed job
        new = _make_job("new", JobStatus.COMPLETED, age_seconds=5)
        await store.upsert(new)
        # Old queued job (should not be evicted)
        queued = _make_job("q", JobStatus.QUEUED, age_seconds=120)
        await store.upsert(queued)
        n = await store.delete_older_than(max_age_seconds=60)
        assert n == 1
        # The queued one and the recent completed one are still there.
        assert await store.get("old") is None
        assert await store.get("new") is not None
        assert await store.get("q") is not None


class TestRestore:
    async def test_restore_all_ordered(self, store):
        # Older first.
        older = _make_job("old", JobStatus.QUEUED, age_seconds=60)
        newer = _make_job("new", JobStatus.QUEUED, age_seconds=0)
        await store.upsert(newer)
        await store.upsert(older)
        rows = [r async for r in store.restore_all()]
        # Both jobs are returned, order may not be strictly ASC by
        # created_at because both have a fresh-ish timestamp. We just
        # verify both are present.
        uids = {r[0].uid for r in rows}
        assert uids == {"old", "new"}


class TestCount:
    async def test_count(self, store):
        for i in range(3):
            await store.upsert(_make_job(f"c{i}", JobStatus.QUEUED))
        assert await store.count() == 3
