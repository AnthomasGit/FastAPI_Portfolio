import os
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SceneStaging, SceneCapture, Asset3D, Scene

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")


async def get_or_create_staging(scene_id: str, db: AsyncSession) -> SceneStaging:
    result = await db.execute(
        select(SceneStaging).where(SceneStaging.scene_id == scene_id)
    )
    staging = result.scalars().first()
    if staging:
        return staging

    scene_result = await db.execute(select(Scene).where(Scene.id == scene_id))
    if not scene_result.scalars().first():
        raise ValueError("Scene not found")

    staging = SceneStaging(scene_id=scene_id)
    db.add(staging)
    await db.commit()
    await db.refresh(staging)
    return staging


async def update_staging(
    scene_id: str,
    db: AsyncSession,
    camera: dict | None = None,
    blockout: list | None = None,
    placements: list | None = None,
    backdrop_reference_id: str | None = None,
) -> SceneStaging:
    staging = await get_or_create_staging(scene_id, db)

    if placements is not None:
        scene_result = await db.execute(select(Scene).where(Scene.id == scene_id))
        scene = scene_result.scalars().first()
        if not scene:
            raise ValueError("Scene not found")
        project_id = scene.project_id

        for placement in placements:
            asset_id = placement.get("asset3d_id")
            if not asset_id:
                raise ValueError("Each placement must have an asset3d_id")
            asset_result = await db.execute(
                select(Asset3D).where(
                    Asset3D.id == asset_id,
                    Asset3D.project_id == project_id,
                )
            )
            if not asset_result.scalars().first():
                raise ValueError(
                    f"Asset3D {asset_id} not found or does not belong to this project"
                )

    if camera is not None:
        staging.camera = camera
    if blockout is not None:
        staging.blockout = blockout
    if placements is not None:
        staging.placements = placements
    if backdrop_reference_id is not None:
        staging.backdrop_reference_id = backdrop_reference_id

    staging.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(staging)
    return staging


async def create_capture(
    scene_id: str,
    depth_map_data: bytes,
    camera: dict,
    width: int,
    height: int,
    edge_map_data: bytes | None = None,
    db: AsyncSession | None = None,
) -> SceneCapture:
    staging = await get_or_create_staging(scene_id, db)

    depth_filename = f"depth_{uuid.uuid4()}.png"
    depth_path = os.path.join(COMFY_INPUT_DIR, depth_filename)
    with open(depth_path, "wb") as f:
        f.write(depth_map_data)

    edge_filename = None
    if edge_map_data:
        edge_filename = f"edge_{uuid.uuid4()}.png"
        edge_path = os.path.join(COMFY_INPUT_DIR, edge_filename)
        with open(edge_path, "wb") as f:
            f.write(edge_map_data)

    snapshot = {
        "blockout": staging.blockout,
        "placements": staging.placements,
        "backdrop_reference_id": staging.backdrop_reference_id,
    }

    capture = SceneCapture(
        staging_id=staging.id,
        camera=camera,
        staging_snapshot=snapshot,
        depth_map_url=depth_filename,
        edge_map_url=edge_filename,
        width=width,
        height=height,
    )
    db.add(capture)
    await db.commit()
    await db.refresh(capture)
    return capture


async def get_captures(scene_id: str, db: AsyncSession) -> list[SceneCapture]:
    result = await db.execute(
        select(SceneStaging).where(SceneStaging.scene_id == scene_id)
    )
    staging = result.scalars().first()
    if not staging:
        return []

    captures = await db.execute(
        select(SceneCapture)
        .where(SceneCapture.staging_id == staging.id)
        .order_by(SceneCapture.created_at.desc())
    )
    return captures.scalars().all()


async def get_capture_depth(capture_id: str, db: AsyncSession) -> bytes | None:
    result = await db.execute(
        select(SceneCapture).where(SceneCapture.id == capture_id)
    )
    capture = result.scalars().first()
    if not capture or not capture.depth_map_url:
        return None

    filepath = os.path.join(COMFY_INPUT_DIR, capture.depth_map_url)
    try:
        with open(filepath, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


async def delete_capture(capture_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(SceneCapture).where(SceneCapture.id == capture_id)
    )
    capture = result.scalars().first()
    if not capture:
        return False

    await db.delete(capture)
    await db.commit()
    return True
