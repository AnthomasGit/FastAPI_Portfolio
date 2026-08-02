"""Driving-video library: upload validation, listing, deletion.

Videos can't be PIL-verified like images, so the content-type + extension
allowlist IS the validation — this suite exists to prove that gate actually
rejects what it should and accepts what it should.
"""
import os

import pytest

COMFY_INPUT_DIR = os.environ["COMFY_INPUT_DIR"]


@pytest.mark.asyncio
async def test_upload_rejects_non_video_content_type(client):
    resp = await client.post(
        "/api/driving-videos",
        files={"file": ("clip.mp4", b"not really a video", "text/plain")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_disallowed_extension(client):
    resp = await client.post(
        "/api/driving-videos",
        files={"file": ("clip.avi", b"fake", "video/x-msvideo")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_accepts_mp4_and_writes_to_input_dir(client):
    resp = await client.post(
        "/api/driving-videos",
        files={"file": ("walk.mp4", b"fake mp4 bytes", "video/mp4")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["video_url"].endswith(".mp4")
    assert body["content_type"] == "video/mp4"
    assert body["size_bytes"] == len(b"fake mp4 bytes")
    assert os.path.exists(os.path.join(COMFY_INPUT_DIR, body["video_url"]))


@pytest.mark.asyncio
async def test_upload_stores_label_and_project(client, project):
    resp = await client.post(
        f"/api/driving-videos?project_id={project.id}&label=Walking%20loop",
        files={"file": ("walk.mp4", b"fake", "video/mp4")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["origin_project_id"] == project.id
    assert body["label"] == "Walking loop"


@pytest.mark.asyncio
async def test_list_returns_newest_first(client):
    first = (await client.post(
        "/api/driving-videos", files={"file": ("a.mp4", b"a", "video/mp4")},
    )).json()
    second = (await client.post(
        "/api/driving-videos", files={"file": ("b.mp4", b"b", "video/mp4")},
    )).json()

    resp = await client.get("/api/driving-videos")
    assert resp.status_code == 200
    ids = [v["id"] for v in resp.json()]
    assert ids.index(second["id"]) < ids.index(first["id"])


@pytest.mark.asyncio
async def test_list_filters_by_project_but_is_not_scoped_by_default(client, project):
    scoped = (await client.post(
        f"/api/driving-videos?project_id={project.id}",
        files={"file": ("a.mp4", b"a", "video/mp4")},
    )).json()
    unscoped = (await client.post(
        "/api/driving-videos", files={"file": ("b.mp4", b"b", "video/mp4")},
    )).json()

    # The library is reusable across projects by design: no filter returns both.
    all_ids = {v["id"] for v in (await client.get("/api/driving-videos")).json()}
    assert {scoped["id"], unscoped["id"]} <= all_ids

    # An explicit project_id narrows to just that project's uploads.
    filtered = await client.get(f"/api/driving-videos?project_id={project.id}")
    filtered_ids = {v["id"] for v in filtered.json()}
    assert scoped["id"] in filtered_ids
    assert unscoped["id"] not in filtered_ids


@pytest.mark.asyncio
async def test_delete_removes_row_and_file(client):
    created = (await client.post(
        "/api/driving-videos", files={"file": ("gone.mp4", b"x", "video/mp4")},
    )).json()
    filepath = os.path.join(COMFY_INPUT_DIR, created["video_url"])
    assert os.path.exists(filepath)

    resp = await client.delete(f"/api/driving-videos/{created['id']}")
    assert resp.status_code == 204
    assert not os.path.exists(filepath)

    listed = await client.get("/api/driving-videos")
    assert created["id"] not in {v["id"] for v in listed.json()}


@pytest.mark.asyncio
async def test_delete_missing_returns_404(client):
    resp = await client.delete("/api/driving-videos/nonexistent-id")
    assert resp.status_code == 404
