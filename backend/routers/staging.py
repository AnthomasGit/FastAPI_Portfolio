import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db
from schemas.schemas import (
    SceneStagingUpdate,
    SceneStagingResponse,
    SceneCaptureResponse,
    StagingSaveCreate,
    StagingSaveResponse,
)
from services.staging_service import (
    get_or_create_staging,
    update_staging,
    create_capture,
    get_captures,
    get_capture_depth,
    get_capture_color,
    get_capture_normal,
    get_capture_seg,
    delete_capture,
    create_save,
    list_saves,
    restore_save,
    update_save,
    delete_save,
)

router = APIRouter()


@router.get("/api/scenes/{scene_id}/staging", response_model=SceneStagingResponse)
async def get_staging(scene_id: str, db: AsyncSession = Depends(get_db)):
    try:
        staging = await get_or_create_staging(scene_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return staging


@router.put("/api/scenes/{scene_id}/staging", response_model=SceneStagingResponse)
async def put_staging(
    scene_id: str,
    data: SceneStagingUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        staging = await update_staging(
            scene_id, db,
            camera=data.camera,
            blockout=data.blockout,
            placements=data.placements,
            backdrop_reference_id=data.backdrop_reference_id,
            backdrop_transform=data.backdrop_transform,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return staging


@router.post(
    "/api/scenes/{scene_id}/staging/captures",
    status_code=201,
    response_model=SceneCaptureResponse,
)
async def post_capture(
    scene_id: str,
    depth_map: UploadFile = File(...),
    camera: str = Form(...),
    width: int = Form(...),
    height: int = Form(...),
    edge_map: UploadFile | None = File(None),
    color_map: UploadFile | None = File(None),
    normal_map: UploadFile | None = File(None),
    seg_map: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        camera_dict = json.loads(camera)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid camera JSON")

    depth_data = await depth_map.read()
    edge_data = await edge_map.read() if edge_map else None
    color_data = await color_map.read() if color_map else None
    normal_data = await normal_map.read() if normal_map else None
    seg_data = await seg_map.read() if seg_map else None

    try:
        capture = await create_capture(
            scene_id, depth_data, camera_dict, width, height,
            edge_data, color_data, normal_data, seg_data, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return capture


@router.get(
    "/api/scenes/{scene_id}/staging/captures",
    response_model=List[SceneCaptureResponse],
)
async def list_captures(scene_id: str, db: AsyncSession = Depends(get_db)):
    return await get_captures(scene_id, db)


@router.post(
    "/api/scenes/{scene_id}/staging/saves",
    status_code=201,
    response_model=StagingSaveResponse,
)
async def post_staging_save(
    scene_id: str,
    data: StagingSaveCreate,
    db: AsyncSession = Depends(get_db),
):
    if not data.name.strip():
        raise HTTPException(status_code=422, detail="Save name cannot be empty")
    try:
        save = await create_save(scene_id, data.name.strip(), db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return save


@router.get(
    "/api/scenes/{scene_id}/staging/saves",
    response_model=List[StagingSaveResponse],
)
async def list_staging_saves(scene_id: str, db: AsyncSession = Depends(get_db)):
    return await list_saves(scene_id, db)


@router.post("/api/staging-saves/{save_id}/restore", response_model=SceneStagingResponse)
async def restore_staging_save(save_id: str, db: AsyncSession = Depends(get_db)):
    try:
        staging = await restore_save(save_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if staging is None:
        raise HTTPException(status_code=404, detail="Staging save not found")
    return staging


@router.put("/api/staging-saves/{save_id}", response_model=StagingSaveResponse)
async def overwrite_staging_save(save_id: str, db: AsyncSession = Depends(get_db)):
    save = await update_save(save_id, db)
    if save is None:
        raise HTTPException(status_code=404, detail="Staging save not found")
    return save


@router.delete("/api/staging-saves/{save_id}", status_code=204)
async def delete_staging_save(save_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await delete_save(save_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Staging save not found")


@router.get("/api/captures/{capture_id}/depth")
async def get_depth_map(capture_id: str, db: AsyncSession = Depends(get_db)):
    content = await get_capture_depth(capture_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Depth map not found")
    return Response(content=content, media_type="image/png")


@router.get("/api/captures/{capture_id}/color")
async def get_color_map(capture_id: str, db: AsyncSession = Depends(get_db)):
    content = await get_capture_color(capture_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Color frame not found")
    return Response(content=content, media_type="image/png")


@router.get("/api/captures/{capture_id}/normal")
async def get_normal_map(capture_id: str, db: AsyncSession = Depends(get_db)):
    content = await get_capture_normal(capture_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Normal map not found")
    return Response(content=content, media_type="image/png")


@router.get("/api/captures/{capture_id}/seg")
async def get_seg_map(capture_id: str, db: AsyncSession = Depends(get_db)):
    content = await get_capture_seg(capture_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Segmentation map not found")
    return Response(content=content, media_type="image/png")


@router.delete("/api/captures/{capture_id}", status_code=204)
async def delete_capture_endpoint(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_capture(capture_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Capture not found")
