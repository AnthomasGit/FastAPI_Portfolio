import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db
from schemas.schemas import SceneStagingUpdate, SceneStagingResponse, SceneCaptureResponse
from services.staging_service import (
    get_or_create_staging,
    update_staging,
    create_capture,
    get_captures,
    get_capture_depth,
    delete_capture,
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
    db: AsyncSession = Depends(get_db),
):
    try:
        camera_dict = json.loads(camera)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid camera JSON")

    depth_data = await depth_map.read()
    edge_data = await edge_map.read() if edge_map else None

    try:
        capture = await create_capture(
            scene_id, depth_data, camera_dict, width, height, edge_data, db,
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


@router.get("/api/captures/{capture_id}/depth")
async def get_depth_map(capture_id: str, db: AsyncSession = Depends(get_db)):
    content = await get_capture_depth(capture_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Depth map not found")
    return Response(content=content, media_type="image/png")


@router.delete("/api/captures/{capture_id}", status_code=204)
async def delete_capture_endpoint(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_capture(capture_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Capture not found")
