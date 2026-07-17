from pydantic import BaseModel, model_validator
from typing import Any, Optional, List
from datetime import datetime


class ProjectCreate(BaseModel):
    title: Optional[str] = None
    idea: str


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    story_summary: Optional[str] = None
    status: Optional[str] = None


class ProjectListItem(BaseModel):
    id: str
    title: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CharacterCreate(BaseModel):
    name: str
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None


class CharacterResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def derive_reference_url(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            try:
                refs = data.references
            except Exception:
                return data
            primary = next((r for r in (refs or []) if getattr(r, 'role', None) == 'primary'), None)
            if primary and getattr(primary, 'url', None):
                return {
                    'id': data.id,
                    'project_id': data.project_id,
                    'name': data.name,
                    'description': data.description,
                    'traits': data.traits,
                    'reference_url': primary.url,
                }
        return data


class LocationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    shot_notes: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    shot_notes: Optional[str] = None


class LocationResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    shot_notes: Optional[str] = None

    class Config:
        from_attributes = True


class PropCreate(BaseModel):
    name: str
    description: Optional[str] = None


class PropUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PropResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class ReferenceCreate(BaseModel):
    url: str
    role: str = "moodboard"
    description: Optional[str] = None


class ReferenceUpdate(BaseModel):
    role: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class ReferenceResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    role: str
    url: Optional[str] = None
    processed_url: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    asset_image_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AssetImageGenerateRequest(BaseModel):
    project_id: str
    entity_type: str
    entity_id: Optional[str] = None
    prompt: Optional[str] = None
    source_reference_id: Optional[str] = None
    source_asset_image_id: Optional[str] = None


class AssetImageResponse(BaseModel):
    id: str
    origin_project_id: Optional[str] = None
    entity_type: str
    kind: str = "txt2img"
    source_reference_id: Optional[str] = None
    source_asset_image_id: Optional[str] = None
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    status: str = "queued"
    job_id: Optional[str] = None
    prompt_id: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Asset3DMeshGenerateRequest(BaseModel):
    entity_type: str
    entity_id: str
    reference_id: Optional[str] = None
    params: Optional[dict] = None


class Asset3DResponse(BaseModel):
    id: str
    project_id: str
    entity_type: str
    entity_id: str
    source_reference_id: Optional[str] = None
    status: str = "queued"
    mesh_url: Optional[str] = None
    rigged_mesh_url: Optional[str] = None
    preview_url: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssetImageAssignRequest(BaseModel):
    asset_image_id: str


class SceneStagingUpdate(BaseModel):
    camera: Optional[dict] = None
    blockout: Optional[list] = None
    placements: Optional[list] = None
    backdrop_reference_id: Optional[str] = None
    backdrop_transform: Optional[dict] = None


class SceneStagingResponse(BaseModel):
    id: str
    scene_id: str
    backdrop_reference_id: Optional[str] = None
    backdrop_transform: Optional[dict] = None
    camera: Optional[dict] = None
    blockout: Optional[list] = None
    placements: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StagingSaveCreate(BaseModel):
    name: str


class StagingSaveResponse(BaseModel):
    id: str
    scene_id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class SceneCaptureResponse(BaseModel):
    id: str
    staging_id: str
    camera: dict
    staging_snapshot: dict
    depth_map_url: str
    edge_map_url: Optional[str] = None
    color_map_url: Optional[str] = None
    width: int
    height: int
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateImageResponse(BaseModel):
    id: str
    scene_id: Optional[str] = None
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    status: str
    job_id: Optional[str] = None

    class Config:
        from_attributes = True


class SceneCreate(BaseModel):
    scene_number: int
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = 0


class SceneUpdate(BaseModel):
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None


class SceneResponse(BaseModel):
    id: str
    project_id: str
    scene_number: int
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None
    sort_order: int
    characters: List[CharacterResponse] = []
    locations: List[LocationResponse] = []
    props: List[PropResponse] = []
    references: List[ReferenceResponse] = []
    generated_images: List[GenerateImageResponse] = []

    class Config:
        from_attributes = True


class ProjectResponse(BaseModel):
    id: str
    title: Optional[str] = None
    idea: str
    clarifications: Optional[dict] = None
    story_summary: Optional[str] = None
    status: str
    created_at: datetime
    scenes: List[SceneResponse] = []
    characters: List[CharacterResponse] = []
    locations: List[LocationResponse] = []
    props: List[PropResponse] = []

    class Config:
        from_attributes = True


class ClarifyRequest(BaseModel):
    idea: str


class ClarifyResponse(BaseModel):
    questions: List[str]


class GenerateStoryboardRequest(BaseModel):
    idea: str
    answers: dict


class StoryboardResponse(BaseModel):
    project_id: str
    message: str


class SceneReorderRequest(BaseModel):
    scene_ids: List[str]


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    data: dict


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class GraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
