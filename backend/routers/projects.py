from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Project, Scene, Character, Location, Prop
from schemas.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListItem,
    GraphNode, GraphEdge, GraphResponse
)
from services.scene_link_service import load_scene_links, build_scene_response

router = APIRouter()


@router.get("/api/projects", response_model=List[ProjectListItem])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.post("/api/projects", status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(title=data.title, idea=data.idea)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {"project_id": project.id, "status": project.status}


@router.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Project)
        .options(
            selectinload(Project.scenes)
                .selectinload(Scene.characters),
            selectinload(Project.scenes)
                .selectinload(Scene.locations),
            selectinload(Project.scenes)
                .selectinload(Scene.props),
            selectinload(Project.scenes)
                .selectinload(Scene.references),
            selectinload(Project.scenes)
                .selectinload(Scene.generated_images),
            selectinload(Project.characters),
            selectinload(Project.locations),
            selectinload(Project.props),
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    resp = ProjectResponse.model_validate(project)
    links = await load_scene_links(db, [s.id for s in project.scenes])
    resp.scenes = [build_scene_response(s, links[s.id]) for s in project.scenes]
    return resp


@router.put("/api/projects/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if data.title is not None:
        project.title = data.title
    if data.story_summary is not None:
        project.story_summary = data.story_summary
    if data.status is not None:
        project.status = data.status
    await db.commit()
    await db.refresh(project)
    return {"project_id": project.id, "status": project.status}


@router.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()


@router.get("/api/projects/{project_id}/graph", response_model=GraphResponse)
async def get_project_graph(project_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Project)
        .options(
            selectinload(Project.scenes)
                .selectinload(Scene.characters),
            selectinload(Project.scenes)
                .selectinload(Scene.locations),
            selectinload(Project.scenes)
                .selectinload(Scene.props),
            selectinload(Project.characters),
            selectinload(Project.locations),
            selectinload(Project.props),
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    nodes = []
    edges = []
    seen_ids = set()

    for scene in project.scenes:
        scene_id = f"scene-{scene.id}"
        if scene_id not in seen_ids:
            seen_ids.add(scene_id)
            nodes.append(GraphNode(
                id=scene_id,
                type="scene",
                label=f"Scene {scene.scene_number}: {scene.slugline or 'Untitled'}",
                data={"scene_number": scene.scene_number, "slugline": scene.slugline or ""}
            ))

        for char in scene.characters:
            char_id = f"character-{char.id}"
            if char_id not in seen_ids:
                seen_ids.add(char_id)
                nodes.append(GraphNode(
                    id=char_id,
                    type="character",
                    label=char.name,
                    data={"description": char.description or ""}
                ))
            edges.append(GraphEdge(
                id=f"e-{scene_id}-{char_id}",
                source=scene_id,
                target=char_id,
                label="features"
            ))

        for loc in scene.locations:
            loc_id = f"location-{loc.id}"
            if loc_id not in seen_ids:
                seen_ids.add(loc_id)
                nodes.append(GraphNode(
                    id=loc_id,
                    type="location",
                    label=loc.name,
                    data={"description": loc.description or ""}
                ))
            edges.append(GraphEdge(
                id=f"e-{scene_id}-{loc_id}",
                source=scene_id,
                target=loc_id,
                label="set in"
            ))

        for prop in scene.props:
            prop_id = f"prop-{prop.id}"
            if prop_id not in seen_ids:
                seen_ids.add(prop_id)
                nodes.append(GraphNode(
                    id=prop_id,
                    type="prop",
                    label=prop.name,
                    data={"description": prop.description or ""}
                ))
            edges.append(GraphEdge(
                id=f"e-{scene_id}-{prop_id}",
                source=scene_id,
                target=prop_id,
                label="uses"
            ))

    return GraphResponse(nodes=nodes, edges=edges)
