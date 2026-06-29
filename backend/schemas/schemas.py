from pydantic import BaseModel
from typing import Optional, List
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
    url: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None


class ReferenceResponse(BaseModel):
    id: str
    scene_id: str
    url: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None

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
