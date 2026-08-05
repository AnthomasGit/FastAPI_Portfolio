"""KAN-31 — output size estimate + prune script."""
import os
import uuid
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from database import Scene, Batch
import services.batch_service as bs
from scripts.prune_outputs import find_prunable, run_prune


async def _scenes(db_session, project, n):
    for i in range(n):
        db_session.add(Scene(id=str(uuid.uuid4()), project_id=project.id,
                             scene_number=i + 1, slugline=f"S{i}", screenplay="x",
                             sort_order=i))
    await db_session.commit()


# ── estimate arithmetic ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_estimate_is_jobs_times_kind_average(db_session, project):
    await _scenes(db_session, project, 4)
    spec = {"project_id": project.id, "scope": "project", "kind": "scene_image",
            "variants": 2}
    est, count = await bs.estimate_output_bytes(spec, db_session)
    assert count == 8  # 4 scenes x 2 variants
    assert est == 8 * bs.KIND_AVG_BYTES["scene_image"]


@pytest.mark.asyncio
async def test_estimate_included_in_response(client, db_session, project, monkeypatch):
    await _scenes(db_session, project, 3)
    monkeypatch.setattr(bs, "free_output_bytes", lambda: 1 << 60)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
    })
    assert resp.status_code == 201
    assert resp.json()["estimated_output_bytes"] == 3 * bs.KIND_AVG_BYTES["scene_image"]


# ── 507 path with a stubbed free-disk value ────────────────────────────────

@pytest.mark.asyncio
async def test_insufficient_disk_returns_507_and_creates_nothing(client, db_session, project, monkeypatch):
    await _scenes(db_session, project, 3)
    # Only 1 byte free — the estimate can't possibly fit. Patch the name the
    # router actually calls (imported into its namespace).
    monkeypatch.setattr("routers.batches.free_output_bytes", lambda: 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
    })
    assert resp.status_code == 507
    assert (await db_session.execute(select(Batch))).scalars().first() is None


# ── prune: dry-run lists the right files, deletes nothing ──────────────────

def _write_old(path, days_old=30):
    with open(path, "wb") as f:
        f.write(b"x")
    old = time.time() - days_old * 86400
    os.utime(path, (old, old))


def test_find_prunable_keeps_referenced_and_recent(tmp_path):
    out = tmp_path
    _write_old(out / "orphan_00001_.png", days_old=30)          # unreferenced, old -> prune
    _write_old(out / "kept_00001_.png", days_old=30)            # referenced -> keep
    with open(out / "fresh_00001_.png", "wb") as f:             # unreferenced but new -> keep
        f.write(b"x")

    cutoff = datetime.utcnow() - timedelta(days=7)
    prunable = find_prunable(str(out), referenced={"kept_00001_.png"}, cutoff=cutoff)
    assert prunable == ["orphan_00001_.png"]


def test_run_prune_dry_run_deletes_nothing(tmp_path):
    _write_old(tmp_path / "orphan_a.png", days_old=30)
    _write_old(tmp_path / "orphan_b.png", days_old=30)

    result = run_prune(str(tmp_path), referenced=set(), days=7, apply=False)
    assert sorted(result["prunable"]) == ["orphan_a.png", "orphan_b.png"]
    assert result["deleted"] == []
    # Nothing was actually removed.
    assert (tmp_path / "orphan_a.png").exists()
    assert (tmp_path / "orphan_b.png").exists()


def test_run_prune_apply_deletes(tmp_path):
    _write_old(tmp_path / "orphan_a.png", days_old=30)
    result = run_prune(str(tmp_path), referenced=set(), days=7, apply=True)
    assert result["deleted"] == ["orphan_a.png"]
    assert not (tmp_path / "orphan_a.png").exists()
