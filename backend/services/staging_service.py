import os
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SceneStaging, SceneCapture, StagingSave, Asset3D, Scene

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
    backdrop_transform: dict | None = None,
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
    if backdrop_transform is not None:
        staging.backdrop_transform = backdrop_transform

    staging.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(staging)
    return staging


def _write_capture_file(prefix: str, data: bytes) -> str:
    filename = f"{prefix}_{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, filename), "wb") as f:
        f.write(data)
    return filename


async def create_capture(
    scene_id: str,
    depth_map_data: bytes,
    camera: dict,
    width: int,
    height: int,
    edge_map_data: bytes | None = None,
    color_map_data: bytes | None = None,
    normal_map_data: bytes | None = None,
    seg_map_data: bytes | None = None,
    db: AsyncSession | None = None,
) -> SceneCapture:
    staging = await get_or_create_staging(scene_id, db)

    depth_filename = _write_capture_file("depth", depth_map_data)
    edge_filename = _write_capture_file("edge", edge_map_data) if edge_map_data else None
    color_filename = _write_capture_file("color", color_map_data) if color_map_data else None
    normal_filename = _write_capture_file("normal", normal_map_data) if normal_map_data else None
    seg_filename = _write_capture_file("seg", seg_map_data) if seg_map_data else None

    snapshot = {
        "blockout": staging.blockout,
        "placements": staging.placements,
        "backdrop_reference_id": staging.backdrop_reference_id,
        "backdrop_transform": staging.backdrop_transform,
    }

    capture = SceneCapture(
        staging_id=staging.id,
        camera=camera,
        staging_snapshot=snapshot,
        depth_map_url=depth_filename,
        edge_map_url=edge_filename,
        color_map_url=color_filename,
        normal_map_url=normal_filename,
        seg_map_url=seg_filename,
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


async def _read_capture_file(capture_id: str, db: AsyncSession, url_attr: str) -> bytes | None:
    result = await db.execute(
        select(SceneCapture).where(SceneCapture.id == capture_id)
    )
    capture = result.scalars().first()
    filename = getattr(capture, url_attr, None) if capture else None
    if not filename:
        return None

    try:
        with open(os.path.join(COMFY_INPUT_DIR, filename), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


async def get_capture_depth(capture_id: str, db: AsyncSession) -> bytes | None:
    return await _read_capture_file(capture_id, db, "depth_map_url")


async def get_capture_color(capture_id: str, db: AsyncSession) -> bytes | None:
    return await _read_capture_file(capture_id, db, "color_map_url")


async def get_capture_normal(capture_id: str, db: AsyncSession) -> bytes | None:
    return await _read_capture_file(capture_id, db, "normal_map_url")


async def get_capture_seg(capture_id: str, db: AsyncSession) -> bytes | None:
    return await _read_capture_file(capture_id, db, "seg_map_url")


async def create_save(scene_id: str, name: str, db: AsyncSession) -> StagingSave:
    staging = await get_or_create_staging(scene_id, db)

    save = StagingSave(
        scene_id=scene_id,
        name=name,
        backdrop_reference_id=staging.backdrop_reference_id,
        backdrop_transform=staging.backdrop_transform,
        camera=staging.camera,
        blockout=staging.blockout,
        placements=staging.placements,
    )
    db.add(save)
    await db.commit()
    await db.refresh(save)
    return save


async def list_saves(scene_id: str, db: AsyncSession) -> list[StagingSave]:
    result = await db.execute(
        select(StagingSave)
        .where(StagingSave.scene_id == scene_id)
        .order_by(StagingSave.created_at.desc())
    )
    return result.scalars().all()


async def restore_save(save_id: str, db: AsyncSession) -> SceneStaging | None:
    result = await db.execute(
        select(StagingSave).where(StagingSave.id == save_id)
    )
    save = result.scalars().first()
    if not save:
        return None

    staging = await update_staging(
        save.scene_id, db,
        blockout=save.blockout or [],
        placements=save.placements or [],
    )
    # update_staging skips None values; a restore must match the save exactly,
    # including fields that were empty when it was taken
    staging.camera = save.camera
    staging.backdrop_reference_id = save.backdrop_reference_id
    staging.backdrop_transform = save.backdrop_transform
    staging.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(staging)
    return staging


async def update_save(save_id: str, db: AsyncSession) -> StagingSave | None:
    result = await db.execute(
        select(StagingSave).where(StagingSave.id == save_id)
    )
    save = result.scalars().first()
    if not save:
        return None

    staging = await get_or_create_staging(save.scene_id, db)
    save.backdrop_reference_id = staging.backdrop_reference_id
    save.backdrop_transform = staging.backdrop_transform
    save.camera = staging.camera
    save.blockout = staging.blockout
    save.placements = staging.placements
    await db.commit()
    await db.refresh(save)
    return save


async def delete_save(save_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(StagingSave).where(StagingSave.id == save_id)
    )
    save = result.scalars().first()
    if not save:
        return False

    await db.delete(save)
    await db.commit()
    return True


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
